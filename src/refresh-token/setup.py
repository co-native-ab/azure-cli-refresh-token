#!/usr/bin/env python

# --------------------------------------------------------------------------------------------
# Licensed under the MIT License. See LICENSE in the repository root for license information.
# --------------------------------------------------------------------------------------------

from codecs import open
from setuptools import setup, find_packages

VERSION = '0.1.0'

CLASSIFIERS = [
    'Development Status :: 4 - Beta',
    'Intended Audience :: Developers',
    'Intended Audience :: System Administrators',
    'Programming Language :: Python',
    'Programming Language :: Python :: 3',
    'Programming Language :: Python :: 3.9',
    'Programming Language :: Python :: 3.10',
    'Programming Language :: Python :: 3.11',
    'Programming Language :: Python :: 3.12',
    'Programming Language :: Python :: 3.13',
    'Programming Language :: Python :: 3.14',
    'License :: OSI Approved :: MIT License',
]

DEPENDENCIES = []

with open('README.md', 'r', encoding='utf-8') as f:
    README = f.read()
with open('HISTORY.rst', 'r', encoding='utf-8') as f:
    HISTORY = f.read()

setup(
    name='refresh-token',
    version=VERSION,
    description='Refresh the access tokens the Azure CLI uses, without signing in again.',
    long_description=README + '\n\n' + HISTORY,
    long_description_content_type='text/markdown',
    license='MIT',
    author='azure-cli-refresh-token contributors',
    url='https://github.com/co-native-ab/azure-cli-refresh-token',
    classifiers=CLASSIFIERS,
    python_requires='>=3.9',
    packages=find_packages(include=['azext_refresh_token']),
    install_requires=DEPENDENCIES,
    package_data={'azext_refresh_token': ['azext_metadata.json']},
)
