import struct
import numpy as np

import ibex.cnns.skeleton.util
from ibex.evaluation.classification import *
from ibex.data_structures import unionfind
from ibex.transforms import seg2seg



def RetrieveCandidates(prefix, model_prefix, threshold, maximum_distance, endpoint_distance, network_distance):
    # get all of the candidates for this brain
    positive_candidates = ibex.cnns.skeleton.util.FindCandidates(prefix, threshold, maximum_distance, endpoint_distance, network_distance, 'positive')
    negative_candidates = ibex.cnns.skeleton.util.FindCandidates(prefix, threshold, maximum_distance, endpoint_distance, network_distance, 'negative')

    candidates = positive_candidates + negative_candidates
    ncandidates = len(candidates)

    # read the probabilities foor this candidate
    probabilities_filename = '{}-{}-{}-{}nm-{}nm-{}nm.probabilities'.format(model_prefix, prefix, threshold, maximum_distance, endpoint_distance, network_distance)
    with open(probabilities_filename, 'rb') as fd:
        nprobabilities, = struct.unpack('i', fd.read(4))
        assert (nprobabilities == ncandidates)
        edge_weights = np.zeros(nprobabilities, dtype=np.float64)
        for iv in range(nprobabilities):
            edge_weights[iv], = struct.unpack('d', fd.read(8))

    # print the statistics
    print '\nCNN Precision and Recall\n'
    labels = np.zeros(ncandidates, dtype=np.uint8)
    for ie, candidate in enumerate(candidates):
        labels[ie] = candidate.ground_truth
    PrecisionAndRecall(labels, Prob2Pred(edge_weights))

    return candidates, edge_weights



# collapse the edges from multicut
def CollapseGraph(segmentation, candidates, collapsed_edges, probabilities):
    ncandidates = len(candidates)

    # get the ground truth and the predictions
    labels = np.zeros(ncandidates, dtype=np.bool)
    for iv in range(ncandidates):
        labels[iv] = candidates[iv].ground_truth

    # create an empty union find data structure
    max_value = np.amax(segmentation) + 1
    union_find = [unionfind.UnionFindElement(iv) for iv in range(max_value)]

    # create adjacency sets for the elements in the segment
    adjacency_sets = [set() for _ in range(ncandidates)]

    for candidate in candidates:
        label_one = candidate.labels[0]
        label_two = candidate.labels[1]

        adjacency_sets[label_one].add(label_two)
        adjacency_sets[label_two].add(label_one)

    # iterate over the candidates in order of decreasing probability
    zipped = zip(probabilities, [ie for ie in range(ncandidates)])

    for probability, ie in sorted(zipped, reverse=True):
        # skip if the edge is not collapsed
        if collapsed_edges[ie]: continue
        # skip if this creates a cycle
        label_one, label_two = candidates[ie].labels

        # get the parent of this label
        label_two_union_find = unionfind.Find(union_find[label_two]).label

        # make sure none of the other adjacent nodes already has this label
        for neighbor_label in adjacency_sets[label_one]:
            if neighbor_label == label_two: continue

            if unionfind.Find(union_find[neighbor_label]).label == label_two_union_find: 
                collapsed_edges[ie] = True

        # skip if the edge is no longer collapsed
        if collapsed_edges[ie]: continue
        unionfind.Union(union_find[label_one], union_find[label_two])

    print '\nBorder Constraints\n'
    PrecisionAndRecall(labels, 1 - collapsed_edges)


    # create a mapping for the labels
    mapping = np.zeros(max_value, dtype=np.int64)
    for iv in range(max_value):
        mapping[iv] = unionfind.Find(union_find[iv]).label

    segmentation = seg2seg.MapLabels(segmentation, mapping)

    return segmentation