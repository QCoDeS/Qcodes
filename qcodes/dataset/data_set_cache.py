from typing import TYPE_CHECKING, Dict, Optional, Mapping, Tuple
from copy import copy
import logging

import numpy as np

from qcodes.dataset.descriptions.rundescriber import RunDescriber
from qcodes.dataset.sqlite.queries import (
    load_new_data_for_rundescriber, completed)
from qcodes.dataset.sqlite.connection import ConnectionPlus

if TYPE_CHECKING:
    import pandas as pd

    from .data_set import DataSet, ParameterData


log = logging.getLogger(__name__)


class DataSetCache:
    """
    The DataSetCache contains a in memory representation of the
    data in this dataset as well a a method to progressively read data
    from the db as it is written. The cache is available in the same formats
    as :py:class:`.DataSet.get_parameter_data` and :py:class:`.DataSet.to_pandas_dataframe_dict`

    """

    def __init__(self, dataset: 'DataSet'):
        self._dataset = dataset
        self._data: ParameterData = {}
        #: number of rows read per parameter tree (by the name of the dependent parameter)
        self._read_status: Dict[str, int] = {}
        #: number of rows written per parameter tree (by the name of the dependent parameter)
        self._write_status: Dict[str, Optional[int]] = {}
        self._loaded_from_completed_ds = False

    @property
    def rundescriber(self) -> RunDescriber:
        return self._dataset.description

    def load_data_from_db(self) -> None:
        """
        Loads data from the dataset into the cache.
        If new data has been added to the dataset since the last time
        this method was called, calling this method again would load
        that new portion of the data and append to the already loaded data.
        If the dataset is marked completed and data has already been loaded
        no load will be performed.
        """
        if self._loaded_from_completed_ds:
            return
        self._dataset._completed = completed(
            self._dataset.conn, self._dataset.run_id)
        if self._dataset.completed:
            self._loaded_from_completed_ds = True

        (self._write_status,
         self._read_status,
         self._data) = load_new_data_from_db_and_append(
            self._dataset.conn,
            self._dataset.table_name,
            self.rundescriber,
            self._write_status,
            self._read_status,
            self._data
        )

    def data(self) -> 'ParameterData':
        """
        Loads data from the database on disk if needed and returns
        the cached data. The cached data is in almost the same format as
        :py:class:`.DataSet.get_parameter_data`. However if a shape is provided
        as part of the dataset metadata and fewer datapoints than expected are
        returned the missing values will be replaced by `NaN` or zeroes
        depending on the datatype.

        Returns:
            The cached dataset.
        """
        self.load_data_from_db()
        return self._data

    def to_pandas(self) -> Optional[Dict[str, "pd.DataFrame"]]:
        """
        Convert the cached dataset to Pandas dataframes. The returned dataframes
        are in the same format :py:class:`.DataSet.to_pandas_dataframe_dict`.

        Returns:
            A dict from parameter name to Pandas Dataframes. Each dataframe
            represents one parameter tree.
        """

        self.load_data_from_db()
        if self._data is None:
            return None
        dfs = self._dataset._load_to_dataframe_dict(self._data)
        return dfs


def load_new_data_from_db_and_append(
            conn: ConnectionPlus,
            table_name: str,
            rundescriber: RunDescriber,
            write_status: Dict[str, Optional[int]],
            read_status: Dict[str, int],
            existing_data: Mapping[str, Mapping[str, np.ndarray]],
    ) -> Tuple[Dict[str, Optional[int]],
               Dict[str, int],
               Dict[str, Dict[str, np.ndarray]]]:
    """
    Append any new data in the db to an already existing datadict and return the merged
    data.

    Args:
        conn: The connection to the sqlite database
        table_name: The name of the table the data is stored in
        rundescriber: The rundescriber that describes the run
        write_status: Mapping from dependent parameter name to number of rows
          written to the cache previously.
        read_status: Mapping from dependent parameter name to number of rows
          read from the db previously.
        existing_data: Mapping from dependent parameter name to mapping
          from parameter name to numpy arrays that the data should be
          inserted into.
          appended to.

    Returns:
        Updated write and read status, and the updated ``data``

    """
    new_data, updated_read_status = load_new_data_for_rundescriber(
        conn, table_name, rundescriber, read_status
    )

    (updated_write_status,
     merged_data) = append_shaped_parameter_data_to_existing_arrays(
        rundescriber,
        write_status,
        existing_data,
        new_data
    )
    return updated_write_status, updated_read_status, merged_data


def append_shaped_parameter_data_to_existing_arrays(
        rundescriber: RunDescriber,
        write_status: Dict[str, Optional[int]],
        existing_data: Mapping[str, Mapping[str, np.ndarray]],
        new_data: Mapping[str, Mapping[str, np.ndarray]],
) -> Tuple[Dict[str, Optional[int]],
           Dict[str, Dict[str, np.ndarray]]]:
    """
    Append datadict to an already existing datadict and return the merged
    data.

    Args:
        rundescriber: The rundescriber that describes the run
        write_status: Mapping from dependent parameter name to number of rows
          written to the cache previously.
        new_data: Mapping from dependent parameter name to mapping
          from parameter name to numpy arrays that the data should be
          appended to.
        existing_data: Mapping from dependent parameter name to mapping
          from parameter name to numpy arrays of new data.

    Returns:
        Updated write and read status, and the updated ``data``
    """
    parameters = tuple(ps.name for ps in
                       rundescriber.interdeps.non_dependencies)
    merged_data = {}

    updated_write_status = copy(write_status)

    for meas_parameter in parameters:

        existing_data_1_tree = existing_data.get(meas_parameter, {})

        new_data_1_tree = new_data.get(meas_parameter, {})

        shapes = rundescriber.shapes
        if shapes is not None:
            shape = shapes.get(meas_parameter, None)
        else:
            shape = None

        (merged_data[meas_parameter],
         updated_write_status[meas_parameter]) = _merge_data(
            existing_data_1_tree,
            new_data_1_tree,
            shape,
            single_tree_write_status=write_status.get(meas_parameter)
        )
    return updated_write_status, merged_data


def _merge_data(existing_data: Mapping[str, np.ndarray],
                new_data: Mapping[str, np.ndarray],
                shape: Optional[Tuple[int, ...]],
                single_tree_write_status: Optional[int]
                ) -> Tuple[Dict[str, np.ndarray], Optional[int]]:

    subtree_merged_data = {}
    subtree_parameters = set(existing_data.keys()) | set(new_data.keys())
    new_write_status: Optional[int] = None
    for subtree_param in subtree_parameters:
        existing_values = existing_data.get(subtree_param)
        new_values = new_data.get(subtree_param)
        if existing_values is not None and new_values is not None:
            (subtree_merged_data[subtree_param],
             new_write_status) = _insert_into_data_dict(
                existing_values,
                new_values,
                single_tree_write_status,
                shape=shape
            )
        elif new_values is not None:
            (subtree_merged_data[subtree_param],
             new_write_status) = _create_new_data_dict(
                new_values,
                shape
            )
        elif existing_values is not None:
            subtree_merged_data[subtree_param] = existing_values
            new_write_status = single_tree_write_status

    return subtree_merged_data, new_write_status


def _create_new_data_dict(new_values: np.ndarray,
                          shape: Optional[Tuple[int, ...]]
                          ) -> Tuple[np.ndarray, int]:
    if shape is None:
        return new_values, new_values.size
    else:
        n_values = new_values.size
        data = np.zeros(shape, dtype=new_values.dtype)

        if new_values.dtype.kind == "f" or new_values.dtype.kind == "c":
            data[:] = np.nan

        data.ravel()[0:n_values] = new_values.ravel()
        return data, n_values


def _insert_into_data_dict(
        existing_values: np.ndarray,
        new_values: np.ndarray,
        write_status: Optional[int],
        shape: Optional[Tuple[int, ...]]
) -> Tuple[np.ndarray, Optional[int]]:
    if shape is None or write_status is None:
        return np.append(existing_values, new_values, axis=0), None
    else:
        if existing_values.dtype.kind in ('U', 'S'):
            # string type arrays may be too small for the new data
            # read so rescale if needed.
            if new_values.dtype.itemsize > existing_values.dtype.itemsize:
                existing_values = existing_values.astype(new_values.dtype)
        n_values = new_values.size
        new_write_status = write_status+n_values
        if new_write_status > existing_values.size:
            log.warning(f"Incorrect shape of dataset: Dataset is expected to "
                        f"contain {existing_values.size} points but trying to "
                        f"add an amount of data that makes it contain {new_write_status} points. Cache will "
                        f"be flattened into a 1D array")
            return (np.append(existing_values.flatten(),
                              new_values.flatten(), axis=0),
                    new_write_status)
        else:
            existing_values.ravel()[write_status:new_write_status] = new_values.ravel()
            return existing_values, new_write_status
