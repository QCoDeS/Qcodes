import json
from collections import OrderedDict
from unittest import TestCase

import pytest
import numpy as np

from qcodes.utils.helpers import (is_sequence_of,
                                  compare_dictionaries, NumpyJSONEncoder,
                                  partial_with_docstring)
from qcodes.utils.helpers import attribute_set_to


class A:
    x = 5
    y = 6


class BadKeysDict(dict):
    def keys(self):
        raise RuntimeError('you can\'t have the keys!')


class NoDelDict(dict):
    def __delitem__(self, item):
        raise KeyError('get your hands off me!')


class TestIsSequenceOf(TestCase):
    def test_simple(self):
        good = [
            # empty lists pass without even checking that we provided a
            # valid type spec
            ([], None), ((), None),
            ([1, 2, 3], int),
            ((1, 2, 3), int),
            ([1, 2.0], (int, float)),
            ([{}, None], (type(None), dict)),
            # omit type (or set None) and we don't test type at all
            ([1, '2', dict],),
            ([1, '2', dict], None)
        ]
        for args in good:
            with self.subTest(args=args):
                assert is_sequence_of(*args)

        bad = [
            (1,),
            (1, int),
            ([1, 2.0], int),
            ([1, 2], float),
            ([1, 2], (float, dict))
        ]
        for args in bad:
            with self.subTest(args=args):
                assert not is_sequence_of(*args)

        # second arg, if provided, must be a type or tuple of types
        # failing this doesn't return False, it raises an error
        with pytest.raises(TypeError):
            is_sequence_of([1], 1)
        with pytest.raises(TypeError):
            is_sequence_of([1], (1, 2))

    def test_depth(self):
        good = [
            ([1, 2], int, 1),
            ([[1, 2], [3, 4]], int, 2),
            ([[1, 2.0], []], (int, float), 2),
            ([[[1]]], int, 3),
            ([[1, 2], [3, 4]], None, 2)
        ]
        for args in good:
            with self.subTest(args=args):
                assert is_sequence_of(*args)

        bad = [
            ([1], int, 2),
            ([[1]], int, 1),
            ([[1]], float, 2)
        ]
        for args in bad:
            with self.subTest(args=args):
                assert not is_sequence_of(*args)

    def test_shape(self):
        good = [
            ([1, 2], int, (2,)),
            ([[1, 2, 3], [4, 5, 6.0]], (int, float), (2, 3)),
            ([[[1]]], int, (1, 1, 1)),
            ([[1], [2]], None, (2, 1)),
            # if you didn't have `list` as a type, the shape of this one
            # would be (2, 2) - that's tested in bad below
            ([[1, 2], [3, 4]], list, (2,)),
            (((0, 1, 2), ((0, 1), (0, 1), (0, 1))), tuple, (2,)),
            (((0, 1, 2), ((0, 1), (0, 1), (0, 1))), (tuple, int), (2, 3))
        ]
        for obj, types, shape in good:
            with self.subTest(obj=obj):
                assert is_sequence_of(obj, types, shape=shape)

        bad = [
            ([1], int, (2,)),
            ([[1]], int, (1,)),
            ([[1, 2], [1]], int, (2, 2)),
            ([[1]], float, (1, 1)),
            ([[1, 2], [3, 4]], int, (2, )),
            (((0, 1, 2), ((0, 1), (0, 1))), (tuple, int), (2, 3))
        ]
        for obj, types, shape in bad:
            with self.subTest(obj=obj):
                assert not is_sequence_of(obj, types, shape=shape)

    def test_shape_depth(self):
        # there's no reason to provide both shape and depth, but
        # we allow it if they are self-consistent
        with pytest.raises(ValueError):
            is_sequence_of([], int, depth=1, shape=(2, 2))

        assert not is_sequence_of([1], int, depth=1, shape=(2,))
        assert is_sequence_of([1], int, depth=1, shape=(1,))


# tests related to JSON encoding
class TestJSONencoder(TestCase):

        def test_python_types(self):
            e = NumpyJSONEncoder()

            # test basic python types
            od = OrderedDict()
            od['a'] = 0
            od['b'] = 1
            testinput = [None, True, False, 10, float(10.), 'hello',
                         od]
            testoutput = ['null', 'true', 'false', '10', '10.0', '"hello"',
                          '{"a": 0, "b": 1}']

            for d, r in zip(testinput, testoutput):
                v = e.encode(d)
                if type(d) == dict:
                    assert v == r
                else:
                    assert v == r

        def test_complex_types(self):
            e = NumpyJSONEncoder()
            assert e.encode(complex(1, 2)) == \
                             '{"__dtype__": "complex", "re": 1.0, "im": 2.0}'
            assert e.encode(np.complex(1, 2)) == \
                             '{"__dtype__": "complex", "re": 1.0, "im": 2.0}'
            assert e.encode(np.complex64(complex(1, 2))) == \
                             '{"__dtype__": "complex", "re": 1.0, "im": 2.0}'

        def test_numpy_int_types(self):
            e = NumpyJSONEncoder()

            numpy_ints = (np.int, np.int_, np.int8, np.int16, np.int32,
                          np.int64, np.intc, np.intp,
                          np.uint, np.uint8, np.uint16, np.uint32, np.uint64,
                          np.uintc, np.uintp)

            for int_type in numpy_ints:
                assert e.encode(int_type(3)) == '3'

        def test_numpy_float_types(self):
            e = NumpyJSONEncoder()

            numpy_floats = (np.float, np.float_, np.float16, np.float32,
                            np.float64)

            for float_type in numpy_floats:
                assert e.encode(float_type(2.5)) == '2.5'

        def test_numpy_bool_type(self):
            e = NumpyJSONEncoder()

            assert e.encode(np.bool_(True)) == 'true'
            assert e.encode(np.int8(5) == 5) == 'true'
            assert e.encode(np.array([8, 5]) == 5) == '[false, true]'

        def test_numpy_array(self):
            e = NumpyJSONEncoder()

            assert e.encode(np.array([1, 0, 0])) == \
                             '[1, 0, 0]'

            assert e.encode(np.arange(1.0, 3.0, 1.0)) == \
                             '[1.0, 2.0]'

            assert e.encode(np.meshgrid((1, 2), (3, 4))) == \
                             '[[[1, 2], [1, 2]], [[3, 3], [4, 4]]]'

        def test_non_serializable(self):
            """
            Test that non-serializable objects are serialzed to their
            string representation
            """
            e = NumpyJSONEncoder()

            class Dummy:
                def __str__(self):
                    return 'i am a dummy with \\ slashes /'

            assert e.encode(Dummy()) == \
                             '"i am a dummy with \\\\ slashes /"'

        def test_object_with_serialization_method(self):
            """
            Test that objects with `_JSONEncoder` method are serialized via
            calling that method
            """
            e = NumpyJSONEncoder()

            class Dummy:
                def __init__(self):
                    self.confession = 'a_dict_addict'

                def __str__(self):
                    return 'me as a string'

                def _JSONEncoder(self):
                    return {'i_am_actually': self.confession}

            assert e.encode(Dummy()) == \
                             '{"i_am_actually": "a_dict_addict"}'


class TestCompareDictionaries(TestCase):
    def test_same(self):
        # NOTE(alexcjohnson): the numpy array and list compare equal,
        # even though a list and tuple would not. See TODO in
        # compare_dictionaries.
        a = {'a': 1, 2: [3, 4, {5: 6}], 'b': {'c': 'd'}, 'x': np.array([7, 8])}
        b = {'a': 1, 2: [3, 4, {5: 6}], 'b': {'c': 'd'}, 'x': [7, 8]}

        match, err = compare_dictionaries(a, b)
        assert match
        assert err == ''

    def test_bad_dict(self):
        # NOTE(alexcjohnson):
        # this is a valid dict, but not good JSON because the tuple key cannot
        # be converted into a string.
        # It throws an error in compare_dictionaries, which is likely what we
        # want, but we should be aware of it.
        a = {(5, 6): (7, 8)}
        with pytest.raises(TypeError):
            compare_dictionaries(a, a)

    def test_key_diff(self):
        a = {'a': 1, 'c': 4}
        b = {'b': 1, 'c': 4}

        match, err = compare_dictionaries(a, b)

        assert not match
        assert 'Key d1[a] not in d2' in err
        assert 'Key d2[b] not in d1' in err

        # try again with dict names for completeness
        match, err = compare_dictionaries(a, b, 'a', 'b')

        assert not match
        assert 'Key a[a] not in b' in err
        assert 'Key b[b] not in a' in err

    def test_val_diff_simple(self):
        a = {'a': 1}
        b = {'a': 2}

        match, err = compare_dictionaries(a, b)

        assert not match
        assert 'Value of "d1[a]" ("1", type"<class \'int\'>") not same as' in err
        assert '"d2[a]" ("2", type"<class \'int\'>")' in err

    def test_val_diff_seq(self):
        # NOTE(alexcjohnson):
        # we don't dive recursively into lists at the moment.
        # Perhaps we want to? Seems like list equality does a deep comparison,
        # so it's not necessary to get ``match`` right, but the error message
        # could be more helpful if we did.
        a = {'a': [1, {2: 3}, 4]}
        b = {'a': [1, {5: 6}, 4]}

        match, err = compare_dictionaries(a, b)

        assert not match
        assert 'Value of "d1[a]" ("[1, {2: 3}, 4]", ' \
                      'type"<class \'list\'>") not same' in err
        assert '"d2[a]" ("[1, {5: 6}, 4]", type"<class \'list\'>")' in \
                      err

    def test_nested_key_diff(self):
        a = {'a': {'b': 'c'}}
        b = {'a': {'d': 'c'}}

        match, err = compare_dictionaries(a, b)

        assert not match
        assert 'Key d1[a][b] not in d2' in err
        assert 'Key d2[a][d] not in d1' in err


class TestAttributeSetToContextManager(TestCase):
    """
    Test attribute_set_to context manager
    """

    class X:
        y = 0

    def test_attribute_set_to_value(self):
        """Test setting attribute to a value"""
        x = self.X()
        x.y = 1

        assert 1 == x.y

        with attribute_set_to(x, 'y', 2):
            assert 2 == x.y

        assert 1 == x.y

    def test_attribute_set_to_object(self):
        """Test setting attribute to an object"""
        x = self.X()
        original_object = self.X()
        x.y = original_object

        assert original_object == x.y
        assert original_object is x.y

        new_object = self.X()
        with attribute_set_to(x, 'y', new_object):
            assert new_object == x.y
            assert new_object is x.y

        assert original_object == x.y
        assert original_object is x.y


class TestPartialWithDocstring(TestCase):
    """Test the sane partial function"""
    def test_main(self):
        def f():
            pass

        docstring = "some docstring"
        g = partial_with_docstring(f, docstring)
        assert g.__doc__ == docstring
