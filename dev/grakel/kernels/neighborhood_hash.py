"""The neighborhood hashing kernel as defined in :cite:`Hido2009ALG`."""
import collections
import warnings

from numpy.random import seed
from numpy.random import choice

from grakel.graph import Graph
from grakel.kernels import Kernel

from sklearn.utils.validation import check_is_fitted

# Python 2/3 cross-compatibility import
from six import itervalues
from six import iteritems

default_executor = lambda fn, *eargs, **ekargs: fn(*eargs, **ekargs)


class NeighborhoodHash(Kernel):
    """Neighborhood hashing kernel as proposed in :cite:`Hido2009ALG`.

    Parameters
    ----------
    R : int, default=3
        The maximum number of neighborhood hash.

    nh_type : str, valid_types={"simple", "count_sensitive"}, default="simple"
        The existing neighborhood hash type as defined in :cite:`Hido2009ALG`.

    bytes : int, default=2
        Byte size of hashes.

    random_seed : int, default=15487103
        Random seed for intialising labels.

    Attributes
    ----------
    R : number
        The maximum number of neighborhood hash.

    bits : int
        Defines the bit size of hashes.

    nh_type : str
        The existing neighborhood hash type as defined in :cite:`Hido2009ALG`.

    _NH : function
        The neighborhood hashing function.

    _noc_f : bool
        A flag concerning the number of occurencies metric.

    """

    def __init__(self,
                 executor=default_executor,
                 normalize=False,
                 verbose=False,
                 random_seed=42,
                 R=3,
                 nh_type='simple',
                 bits=8):
        """Initialize a `neighborhood_hash` kernel."""
        super(NeighborhoodHash, self).__init__(executor=executor,
                                               normalize=normalize,
                                               verbose=False)

        self.random_seed = random_seed
        self.R = R
        self.nh_type = nh_type
        self.bits = bits
        self.initialized_ = {"random_seed": False, "R": False, "nh_type": False,
                             "bits": False}

    def initialize_(self):
        """Initialize all transformer arguments, needing initialization."""
        if not self.initialized_["random_seed"]:
            seed(self.random_seed)
            self.initialized_["random_seed"] = True

        if not self.initialized_["R"]:
            if type(self.R) is not int or self.R <= 0:
                raise TypeError('R must be an intger bigger than zero')
            self.initialized_["R"] = True

        if not self.initialized_["nh_type"]:
            if self.nh_type == 'simple':
                self._noc_f = False
                self._NH = lambda G: self.neighborhood_hash_simple(G)
            elif self.nh_type == 'count_sensitive':
                self._noc_f = True
                self._NH = lambda G: self.neighborhood_hash_count_sensitive(G)
            else:
                raise TypeError('unrecognised neighborhood hashing type')
            self.initialized_["nh_type"] = True

        if not self.initialized_["bits"]:
            if type(self.bits) is not int or self.bits <= 0:
                raise TypeError('illegal number of bits for hashing')

            self._max_number = 1 << self.bits
            self._mask = self._max_number-1
            self.initialized_["bits"] = True

    def fit(self, X, y=None):
        """Fit a dataset, for a transformer.

        Parameters
        ----------
        X : iterable
            Each element must be an iterable with at most three features and at
            least one. The first that is obligatory is a valid graph structure
            (adjacency matrix or edge_dictionary) while the second is
            node_labels and the third edge_labels (that fitting the given graph
            format). The train samples.

        y : None
            There is no need of a target in a transformer, yet the pipeline API
            requires this parameter.

        Returns
        -------
        self : object
        Returns self.

        """
        self._method_calling = 1
        self._is_transformed = False
        # Input validation and parsing
        self.initialize_()
        if X is None:
            raise ValueError('`fit` input cannot be None')
        else:
            if not isinstance(X, collections.Iterable):
                raise TypeError('input must be an iterable\n')

            i = 0
            out = list()
            gs = list()
            self._labels_hash_dict, labels_hash_set = dict(), set()
            for (idx, x) in enumerate(iter(X)):
                is_iter = isinstance(x, collections.Iterable)
                if is_iter:
                    x = list(x)
                if is_iter and len(x) in [0, 1, 2, 3]:
                    if len(x) == 0:
                        warnings.warn('Ignoring empty element on index: '
                                      + str(idx))
                        continue
                    elif len(x) == 1:
                        warnings.warn(
                            'Ignoring empty element on index: '
                            + str(i) + '\nLabels must be provided.')
                    else:
                        x = Graph(x[0], x[1], {}, self._graph_format)
                        vertices = list(x.get_vertices(purpose="any"))
                        Labels = x.get_labels(purpose="any")
                elif type(x) is Graph:
                    vertices = list(x.get_vertices(purpose="any"))
                    Labels = x.get_labels(purpose="any")
                else:
                    raise TypeError('each element of X must be either '
                                    'a graph object or a list with at '
                                    'least a graph like object and '
                                    'node labels dict \n')

                g = (vertices, Labels,
                     {n: x.neighbors(n, purpose="any") for n in vertices})

                # collect all the labels
                labels_hash_set |= set(itervalues(Labels))
                gs.append(g)
                i += 1

            if i == 0:
                raise ValueError('parsed input is empty')

            # Hash labels
            if len(labels_hash_set) > self._max_number:
                warnings.warn('Number of labels is smaller than'
                              'the biggest possible.. '
                              'Collisions will appear on the '
                              'new labels.')

                # If labels exceed the biggest possible size
                nl, nrl = list(), len(labels_hash_set)
                while nrl > self._max_number:
                    nl += choice(self._max_number,
                                 self._max_number,
                                 replace=False).tolist()
                    nrl -= self._max_number
                if nrl > 0:
                    nl += choice(self._max_number,
                                 nrl,
                                 replace=False).tolist()
                # unify the collisions per element.

            else:
                # else draw n random numbers.
                nl = choice(self._max_number, len(labels_hash_set),
                            replace=False).tolist()

            self._labels_hash_dict = dict(zip(labels_hash_set, nl))

            # for all graphs
            for vertices, labels, neighbors in gs:
                new_labels = {v: self._labels_hash_dict[l]
                              for v, l in iteritems(labels)}
                g = (vertices, new_labels, neighbors,)
                gr = {0: self._NH(g)}
                for r in range(1, self.R):
                    gr[r] = self._NH(gr[r-1])

                # save the output for all levels
                out.append(gr)

        self.X = out

        # Return the transformer
        return self

    def fit_transform(self, X):
        """Fit and transform, on the same dataset.

        Parameters
        ----------
        X : iterable
            Each element must be an iterable with at most three features and at
            least one. The first that is obligatory is a valid graph structure
            (adjacency matrix or edge_dictionary) while the second is
            node_labels and the third edge_labels (that fitting the given graph
            format). If None the kernel matrix is calculated upon fit data.
            The test samples.

        y : None
            There is no need of a target in a transformer, yet the pipeline API
            requires this parameter.

        Returns
        -------
        K : numpy array, shape = [n_targets, n_input_graphs]
            corresponding to the kernel matrix, a calculation between
            all pairs of graphs between target an features

        """
        self._method_calling = 2
        self.fit(X)

        # Transform - calculate kernel matrix
        # Output is always normalized
        return self._calculate_kernel_matrix()

    def transform(self, X):
        """Calculate the kernel matrix, between given and fitted dataset.

        Parameters
        ----------
        X : iterable
            Each element must be an iterable with at most three features and at
            least one. The first that is obligatory is a valid graph structure
            (adjacency matrix or edge_dictionary) while the second is
            node_labels and the third edge_labels (that fitting the given graph
            format). If None the kernel matrix is calculated upon fit data.
            The test samples.

        Returns
        -------
        K : numpy array, shape = [n_targets, n_input_graphs]
            corresponding to the kernel matrix, a calculation between
            all pairs of graphs between target an features

        """
        self._method_calling = 3
        # Check is fit had been called
        check_is_fitted(self, ['X'])

        # Input validation and parsing
        if X is None:
            raise ValueError('`transform` input cannot be None')
        else:
            if not isinstance(X, collections.Iterable):
                raise TypeError('input must be an iterable\n')

            i = 0
            out = list()
            for (idx, x) in enumerate(iter(X)):
                is_iter = isinstance(x, collections.Iterable)
                if is_iter:
                    x = list(x)
                if is_iter and len(x) in [0, 1, 2, 3]:
                    if len(x) == 0:
                        warnings.warn('Ignoring empty element on index: '
                                      + str(idx))
                        continue
                    elif len(x) == 1:
                        warnings.warn(
                            'Ignoring empty element on index: '
                            + str(i) + '\nLabels must be provided.')
                    else:
                        x = Graph(x[0], x[1], {}, self._graph_format)
                        vertices = list(x.get_vertices(purpose="any"))
                        Labels = x.get_labels(purpose="any")
                elif type(x) is Graph:
                    vertices = list(x.get_vertices(purpose="any"))
                    Labels = x.get_labels(purpose="any")
                else:
                    raise TypeError('each element of X must be either '
                                    'a graph object or a list with at '
                                    'least a graph like object and '
                                    'node labels dict \n')

                # Hash based on the labels of fit
                new_labels = {v: self._labels_hash_dict.get(l, None)
                              for v, l in iteritems(Labels)}

                # Radix sort the other
                g = ((vertices, new_labels) +
                     ({n: x.neighbors(n, purpose="any")
                       for n in vertices},))

                gr = {0: self._NH(g)}
                for r in range(1, self.R):
                    gr[r] = self._NH(gr[r-1])

                # save the output for all levels
                out.append(gr)
                i += 1

                if i == 0:
                    raise ValueError('parsed input is empty')

        # Transform - calculate kernel matrix
        # Output is always normalized
        KM = self._calculate_kernel_matrix(out)
        self._is_transformed = True
        return KM

    def pairwise_operation(self, x, y):
        """Calculate a pairwise kernel between two elements.

        Parameters
        ----------
        x, y : list
            Dict of len=2, tuples, consisting of vertices sorted by
            (labels, vertices) and edge-labels dict, for all levels
            from 0 up to self.R-1.

        Returns
        -------
        kernel : number
            The kernel value.

        """
        k = sum(nh_compare_labels(x[r], y[r]) for r in range(self.R))
        return k / (1.0*self.R)

    def diagonal(self):
        """Calculate the kernel matrix diagonal of the fit/transfromed data.

        Parameters
        ----------
        None.

        Returns
        -------
        X_diag : np.array
            The diagonal of the kernel matrix between the fitted data.
            This consists of each element calculated with itself.

        Y_diag : np.array
            The diagonal of the kernel matrix, of the transform.
            This consists of each element calculated with itself.

        """
        # Output is always normalized
        if self._is_transformed:
            return 1.0, 1.0
        else:
            return 1.0

    def ROT(self, n, d):
        """`rot` operation for binary numbers.

        Parameters
        ----------
        n : int
            The value which will be rotated.

        d : int
            The number of rotations.

        Returns
        -------
        rot : int
            The result of a rot operation.

        """
        m = d % self.bits

        if m > 0:
            return (n << m) & self._mask | \
                   ((n & self._mask) >> (self.bits-m))
        else:
            return n

    def neighborhood_hash_simple(self, G):
        """(simple) neighborhood hashing as defined in :cite:`Hido2009ALG`.

        Parameters
        ----------
        G : tuple
            A tuple of three elements consisting of vertices sorted by labels,
            vertex label dictionary and edge dictionary.

        Returns
        -------
        vertices_labels_edges : tuple
            A tuple of vertices, new_labels-dictionary and edges.

        """
        vertices, labels, neighbors = G
        new_labels = dict()
        for u in vertices:
            if (labels[u] is None or
                    any(labels[n] is None for n in neighbors[u])):
                new_labels[u] = None
            else:
                label = self.ROT(labels[u], 1)
                for n in neighbors[u]:
                    label ^= labels[n]
                new_labels[u] = label
        return tuple(self.vertex_sort_(vertices, new_labels)) + (neighbors,)

    def neighborhood_hash_count_sensitive(self, G):
        """Count sensitive neighborhood hash as defined in :cite:`Hido2009ALG`.

        Parameters
        ----------
        G : tuple, len=3
           A tuple three elements consisting of vertices sorted by labels,
           vertex label dict, edge dict and number of occurencies dict for
           labels.

        Returns
        -------
        vertices_labels_edges_noc : tuple
            A tuple of 4 elements consisting of vertices sorted by labels,
            vertex label dict, edge dict and number of occurencies dict.

        """
        vertices, labels, neighbors = G
        new_labels = dict()
        for u in vertices:
            if (labels[u] is None or
                    any(labels[n] is None for n in neighbors[u])):
                new_labels[u] = None
            else:
                label = self.ROT(labels[u], 1)
                label ^= self.radix_sort_rot([labels[n] is None
                                              for n in neighbors[u]])
                new_labels[u] = label

        return tuple(self.vertex_sort_(vertices, new_labels)) + (neighbors,)

    def radix_sort_rot(self, labels):
        """Sorts vertices based on labels.

        Parameters
        ----------
        labels : dict
            Dictionary of labels for vertices.

        Returns
        -------
        labels_counts : list
            A list of labels with their counts (sorted).

        """
        n = len(labels)
        result = 0
        if n == 0:
            return result

        for b in range(self.bits):
            # The output array elements that will have sorted arr
            output = [0]*n

            # initialize count array as 0
            count = [0, 0]

            # Store count of occurrences in count[]
            for i in range(n):
                count[(labels[i] >> b) % 2] += 1

            # Change count[i] so that count[i] now contains actual
            #  position of this digit in output array
            count[1] += count[0]

            # Build the output array
            for i in range(n-1, -1, -1):
                index = (labels[i] >> b)
                output[count[index % 2] - 1] = labels[i]
                count[index % 2] -= 1

            # Copying the output array to arr[],
            # so that arr now contains sorted numbers
            labels = output

        previous, occ = labels[0], 1
        for i in range(1, len(labels)):
            label = labels[i]
            if label == previous:
                occ += 1
            else:
                result ^= self.ROT(previous ^ occ, occ)
                occ = 1
            previous = label
        if occ > 0:
            result ^= self.ROT(previous ^ occ, occ)
        return result

    def vertex_sort_(self, vertices, labels):
        """Sorts vertices based on labels.

        Parameters
        ----------
        vertices : listable
            A listable of vertices.

        labels : dict
            Dictionary of labels for vertices.

        Returns
        -------
        vertices_labels : tuple, len=2
            The sorted vertices based on labels and labels for vertices.

        """
        if self._method_calling == 3:
            return (sorted(list(vertices),
                           key=lambda x: float('inf')
                           if labels[x] is None else labels[x]), labels)
        else:
            return (sorted(vertices, key=lambda x: labels[x]), labels)


def nh_compare_labels(Gx, Gy):
    """Compare labels function as defined in :cite:`Hido2009ALG`.

    Parameters
    ----------
    G_{x,y} : tuple, len=2
        Graph tuples of two elements, consisting of vertices sorted by
        (labels, vertices) and edge-labels dict.

    Returns
    -------
    kernel : Number
        The kernel value.

    """
    # get vertices
    vx, vy = Gx[0], Gy[0]

    # get size of vertices
    nv_x, nv_y = len(Gx[0]), len(Gy[0])

    # get labels for vertices
    Lx, Ly = Gx[1], Gy[1]

    c, a, b = 0, 0, 0
    while a < nv_x and b < nv_y:
        la = Lx[vx[a]]
        lb = Ly[vy[b]]
        if la is None:
            break
        if la == lb:
            c += 1
            a += 1
            b += 1
        elif la < lb:
            a += 1
        else:
            b += 1

    return c/float(nv_x+nv_y-c)