# coding=utf-8
# Copyright 2018 The TensorFlow Datasets Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Module to use to extract archives. No business logic."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import gzip
import io
import os
import tarfile
import uuid
import zipfile

import concurrent.futures
import promise
import tensorflow as tf

from tensorflow_datasets.core import constants
from tensorflow_datasets.core.download import resource as resource_lib
from tensorflow_datasets.core.utils import py_utils


@py_utils.memoize()
def get_extractor(*args, **kwargs):
  return _Extractor(*args, **kwargs)


class UnsafeArchiveError(Exception):
  """The archive is unsafe to unpack, e.g. absolute path."""


class _Extractor(object):
  """Singleton (use `get_extractor()` module fct) to extract archives."""

  def __init__(self, max_workers=12):
    self._executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=max_workers)

  def extract(self, resource, to_path):
    """Returns `promise.Promise` => to_path."""
    if resource.extract_method not in _EXTRACT_METHODS:
      raise ValueError('Unknonw extraction method "%s".' %
                       resource.extract_method)
    future = self._executor.submit(self._sync_extract, resource, to_path)
    return promise.Promise.resolve(future)

  def _sync_extract(self, resource, to_path):
    """Returns `to_path` once resource has been extracted there."""
    from_path = resource.path
    method = resource.extract_method
    tf.logging.info(
        'Extracting %s (%s) to %s ...' % (from_path, method, to_path))
    to_path_tmp = '%s%s_%s' % (to_path, constants.INCOMPLETE_SUFFIX,
                               uuid.uuid4().hex)
    _EXTRACT_METHODS[method](from_path, to_path_tmp)
    tf.gfile.Rename(to_path_tmp, to_path, overwrite=True)
    tf.logging.info('Finished extracting %s to %s .' % (from_path, to_path))
    return to_path


def _copy(src_file, dest_path):
  """Copy data read from src file obj to new file in dest_path."""
  tf.gfile.MakeDirs(os.path.dirname(dest_path))
  with tf.gfile.Open(dest_path, 'wb') as dest_file:
    while True:
      data = src_file.read(io.DEFAULT_BUFFER_SIZE)
      if not data:
        break
      dest_file.write(data)


def _normpath(path):
  path = os.path.normpath(path)
  if path.startswith('.') or os.path.isabs(path):
    raise UnsafeArchiveError('Archive at %s is not safe.' % path)
  return path


def _extract_tar(src, dst, gz=False):
  read_type = 'r:gz' if gz else 'r'
  with tf.gfile.Open(src, 'rb') as f:
    tar = tarfile.open(mode=read_type, fileobj=f)
    for member in tar.getmembers():
      extract_file = tar.extractfile(member)
      if extract_file:  # File with data (not directory):
        to_path = os.path.join(dst, _normpath(member.path))
        _copy(extract_file, to_path)


def _extract_tar_gz(src, dst):
  _extract_tar(src, dst, gz=True)


def _extract_gzip(src, dst):
  with tf.gfile.Open(src, 'rb') as f:
    gz_file = gzip.GzipFile(fileobj=f)
    _copy(gz_file, dst)


def _extract_zip(src, dst):
  with tf.gfile.Open(src, 'rb') as f:
    z = zipfile.ZipFile(f)
    for member in z.infolist():
      extract_file = z.open(member)
      if extract_file:  # File with data (not directory):
        to_path = os.path.join(dst, _normpath(member.filename))
        _copy(extract_file, to_path)


_EXTRACT_METHODS = {
    resource_lib.ExtractMethod.TAR: _extract_tar,
    resource_lib.ExtractMethod.TAR_GZ: _extract_tar_gz,
    resource_lib.ExtractMethod.GZIP: _extract_gzip,
    resource_lib.ExtractMethod.ZIP: _extract_zip,
}
