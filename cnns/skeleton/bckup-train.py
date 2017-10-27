import time
import numpy as np
import os


from ibex.utilities.constants import *
from ibex.utilities import dataIO
from ibex.cnns.skeleton.util import FindCandidates, ExtractFeature


from keras.models import Sequential
from keras.layers import Activation, BatchNormalization, Convolution3D, Dense, Dropout, Flatten, MaxPooling3D
from keras.layers.advanced_activations import LeakyReLU
from keras.optimizers import Adam, SGD
from keras import backend



# add a convolutional layer to the model
def ConvolutionalLayer(model, filter_size, kernel_size, padding, activation, normalization, input_shape=None):
    if not input_shape == None: model.add(Convolution3D(filter_size, kernel_size, padding=padding, input_shape=input_shape))
    else: model.add(Convolution3D(filter_size, kernel_size, padding=padding))

    # add activation layer
    if activation == 'LeakyReLU': model.add(LeakyReLU(alpha=0.001))
    else: model.add(Activation(activation))
    
    # add normalization after activation
    if normalization: model.add(BatchNormalization())



# add a pooling layer to the model
def PoolingLayer(model, pool_size, dropout, normalization):
    model.add(MaxPooling3D(pool_size=pool_size))

    # add normalization before dropout
    if normalization: model.add(BatchNormalization())

    # add dropout layer
    if dropout > 0.0: model.add(Dropout(dropout))



# add a flattening layer to the model
def FlattenLayer(model):
    model.add(Flatten())



# add a dense layer to the model
def DenseLayer(model, filter_size, dropout, activation, normalization):
    model.add(Dense(filter_size))
    if (dropout > 0.0): model.add(Dropout(dropout))

    # add activation layer
    if activation == 'LeakyReLU': model.add(LeakyReLU(alpha=0.001))
    else: model.add(Activation(activation))

    # add normalization after activation
    if normalization: model.add(BatchNormalization())



def SkeletonNetwork(parameters, width):
    # identify convenient variables
    initial_learning_rate = parameters['initial_learning_rate']
    decay_rate = parameters['decay_rate']
    activation = parameters['activation']
    normalization = parameters['normalization']
    filter_sizes = parameters['filter_sizes']
    depth = parameters['depth']
    betas = parameters['betas']
    assert (len(filter_sizes) >= depth)

    model = Sequential()

    ConvolutionalLayer(model, filter_sizes[0], (3, 3, 3), 'valid', activation, normalization, width)
    ConvolutionalLayer(model, filter_sizes[0], (3, 3, 3), 'valid', activation, normalization)
    PoolingLayer(model, (1, 2, 2), 0.0, normalization)

    ConvolutionalLayer(model, filter_sizes[1], (3, 3, 3), 'valid', activation, normalization)
    ConvolutionalLayer(model, filter_sizes[1], (3, 3, 3), 'valid', activation, normalization)
    PoolingLayer(model, (1, 2, 2), 0.0, normalization)

    ConvolutionalLayer(model, filter_sizes[2], (3, 3, 3), 'valid', activation, normalization)
    ConvolutionalLayer(model, filter_sizes[2], (3, 3, 3), 'valid', activation, normalization)
    PoolingLayer(model, (2, 2, 2), 0.0, normalization)

    if depth > 3:
        ConvolutionalLayer(model, filter_sizes[3], (3, 3, 3), 'valid', activation, normalization)
        ConvolutionalLayer(model, filter_sizes[3], (3, 3, 3), 'valid', activation, normalization)
        PoolingLayer(model, (2, 2, 2), 0.0, normalization)

    FlattenLayer(model)
    DenseLayer(model, 512, 0.0, activation, normalization)
    DenseLayer(model, 1, 0.0, 'sigmoid', False)

    optimizer = Adam(lr=initial_learning_rate, decay=decay_rate, beta_1=betas[0], beta_2=betas[1], epsilon=1e-08)
    model.compile(loss='mean_squared_error', optimizer=optimizer)
    
    return model



# write all relevant information to the log file
def WriteLogfiles(model, model_prefix, parameters):
    logfile = '{}.log'.format(model_prefix)

    with open(logfile, 'w') as fd:
        for layer in model.layers:
            print '{} {} -> {}'.format(layer.get_config()['name'], layer.input_shape, layer.output_shape)
            fd.write('{} {} -> {}\n'.format(layer.get_config()['name'], layer.input_shape, layer.output_shape))
        print 
        fd.write('\n')
        for parameter in parameters:
            print '{}: {}'.format(parameter, parameters[parameter])
            fd.write('{}: {}\n'.format(parameter, parameters[parameter]))



def Train(prefix, model_prefix, threshold, maximum_distance, network_distance, width, parameters):
    # identify convenient variables
    nchannels = width[0]
    starting_epoch = parameters['starting_epoch']
    iterations = parameters['iterations']
    batch_size = parameters['batch_size']
    initial_learning_rate = parameters['initial_learning_rate']
    decay_rate = parameters['decay_rate']

    # architecture parameters
    activation = parameters['activation']
    weights = parameters['weights']
    betas = parameters['betas']
    
    # set up the keras model
    model = SkeletonNetwork(parameters, width)


    
    # make sure the folder for the model prefix exists
    root_location = model_prefix.rfind('/')
    output_folder = model_prefix[:root_location]

    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # open up the log file with no buffer
    logfile = open('{}.log'.format(model_prefix), 'w', 0) 

    # write out the network parameters to a file
    WriteLogfiles(model, model_prefix, parameters)


    
    # read in all relevant information
    segmentation = dataIO.ReadSegmentationData(prefix)
    world_res = dataIO.Resolution(prefix)

    # get the radii for the relevant region
    radii = (network_distance / world_res[IB_Z], network_distance / world_res[IB_Y], network_distance / world_res[IB_X])

    # get all candidates
    candidates = FindCandidates(prefix, threshold, maximum_distance, network_distance, inference=False)
    ncandidates = len(candidates)




    # determine the total number of epochs
    if parameters['augment']: rotations = 16
    else: rotations = 1

    if rotations * ncandidates % batch_size: 
        nepochs = (iterations * rotations * ncandidates / batch_size) + 1
    else:
        nepochs = (iterations * rotations * ncandidates / batch_size)



    # need to adjust learning rate and load in existing weights
    if starting_epoch == 1:
        index = 0
    else:
        nexamples = starting_epoch * batch_size
        current_learning_rate = initial_learning_rate / (1.0 + nexamples * decay_rate)
        backend.set_value(model.optimizer.lr, current_learning_rate)

        index = (starting_epoch * batch_size) % (ncandidates * rotations)

        model.load_weights('{}-{}.h5'.format(model_prefix, starting_epoch))

    # iterate for every epoch
    cumulative_time = time.time()
    for epoch in range(starting_epoch, nepochs + 1):

        # start statistics
        start_time = time.time()

        # create arrays for examples and labels
        examples = np.zeros((batch_size, nchannels, width[IB_Z + 1], width[IB_Y + 1], width[IB_X + 1]), dtype=np.uint8)
        labels = np.zeros(batch_size, dtype=np.uint8)

        for iv in range(batch_size):
            # get the candidate index and the rotation
            rotation = index / ncandidates
            candidate = candidates[index % ncandidates]

            # get the example and label
            examples[iv,:,:,:,:] = ExtractFeature(segmentation, candidate, width, radii, rotation)
            labels[iv] = candidate.ground_truth

            # provide overflow relief
            index += 1
            if index >= ncandidates * rotations: index = 0
        
        
        history = model.fit(examples, labels, batch_size=batch_size, epochs=1, verbose=0, class_weight=weights, shuffle=False)

        # print verbosity
        keras_time = time.time()
        print 'KERAS [Iter {} / {}] loss = {:.7f} Total Time = {:.2f} seconds'.format(epoch, nepochs, history.history['loss'][0], keras_time - start_time)
        
        # save for every 1000 examples
        if not epoch % (1000 / batch_size):
            json_string = model.to_json()
            open('{}-{}.json'.format(model_prefix, epoch), 'w').write(json_string)
            model.save_weights('{}-{}.h5'.format(model_prefix, epoch))

        # update the learning rate
        nexamples = epoch * batch_size
        current_learning_rate = initial_learning_rate / (1.0 + nexamples * decay_rate)
        backend.set_value(model.optimizer.lr, current_learning_rate)



    # save the fully trained model
    json_string = model.to_json()
    open('{}.json'.format(model_prefix), 'w').write(json_string)
    model.save_weights('{}.h5'.format(model_prefix))        