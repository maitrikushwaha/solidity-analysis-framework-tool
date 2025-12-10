'''
Solc Version Selector and Installer

Created on May 22, 2022 by Akshay Fajge
Refactored and Documented on May 7, 2024 by Arnab Mukherjee
'''
import solcx
import operator
import re


class SolcSelector(object):
    # operator map for easy comaprison of versions
    operator_map = {
        '<': operator.lt,
        '<=': operator.le,
        '>=': operator.ge,
        '>': operator.gt,
        '^': operator.ge
    }

    # list of solidity versions
    solidity_versions = ['v0.8.14', 'v0.8.13', 'v0.8.12', 'v0.8.11', 'v0.8.10', 'v0.8.9', 'v0.8.8', 'v0.8.7', 'v0.8.6', 'v0.8.5', 'v0.8.4', 'v0.8.3', 'v0.8.2', 'v0.8.1', 'v0.8.0', 'v0.7.6', 'v0.7.5', 'v0.7.4', 'v0.7.3', 'v0.7.2', 'v0.7.1', 'v0.7.0', 'v0.6.12', 'v0.6.11', 'v0.6.10', 'v0.6.9', 'v0.6.8', 'v0.6.7', 'v0.6.6', 'v0.6.5', 'v0.6.4', 'v0.6.3', 'v0.6.2', 'v0.6.1',
                         'v0.6.0', 'v0.5.17', 'v0.5.16', 'v0.5.15', 'v0.5.14', 'v0.5.13', 'v0.5.12', 'v0.5.11', 'v0.5.10', 'v0.5.9', 'v0.5.8', 'v0.5.7', 'v0.5.6', 'v0.5.5', 'v0.5.4', 'v0.5.3', 'v0.5.2', 'v0.5.1', 'v0.5.0', 'v0.4.26', 'v0.4.25', 'v0.4.24', 'v0.4.23', 'v0.4.22', 'v0.4.21', 'v0.4.20', 'v0.4.19', 'v0.4.18', 'v0.4.17', 'v0.4.16', 'v0.4.15', 'v0.4.14', 'v0.4.13', 'v0.4.12', 'v0.4.11']

    # constructor
    def __init__(self):
        pass

    # install solidity compiler for version passed
    def install_solc_pragma_solc(self, version: str, install=True) -> str:

        # get rid of any whitespace at the start and end of the pragma
        version = version.strip()

        # seperate if multiple versions are provided with an OR clause
        comparator_set_range = [i.strip() for i in version.split('||')]

        # RegEx to extract the solidity version components, including:
        # operator, version, major, minor, patch
        comparator_regex = re.compile(
            r'(?P<operator>([<>]?=?|\^))(?P<version>(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+))')

        # flag to denote whether a suitable compiler version is available or not
        found_version_flag = False

        # traverse through all version of solidity to find out the perfect match for given pragma
        # and install the solidity compiler binary
        for version_json in SolcSelector.solidity_versions:

            # for all versions of solidity mentioned in pragma
            for comparator_set in comparator_set_range:
                # using RegEx, extract and generate dictionary of version information
                # example dict: {'operator': '>=', 'version': '0.4.22', 'major': '0', 'minor': '4', 'patch': '22'}
                # in this case, we obtain a list of such objects / dictionaries
                comparators = [m.groupdict()
                               for m in comparator_regex.finditer(comparator_set)]

                # flag to check whether all comparators satisfy the current listed version (version_json)
                comparator_set_flag = True

                # check if the current selected version from out list of supported version
                # is compatible with the given version (as extracted from the pragma)
                for comparator in comparators:
                    operator = comparator['operator']
                    if not SolcSelector._compare_versions(version_json, comparator['version'], operator):
                        # if version_json (our list item) does not satisfy the comparator version
                        comparator_set_flag = False

                # if compatibility of available version fails,
                # activate range finding
                if comparator_set_flag:
                    found_version_flag = True

            # if range is activated,validate support of version on py-solc-x
            # and install, if required
            if found_version_flag:
                SolcSelector._validate_version(version_json)
                if install:
                    solcx.install_solc(version_json)

                return version_json

        # if everything fails, error out that nothing supports
        raise ValueError("Compatible solc version does not exist")

    @classmethod
    def _validate_version(cls, version: str) -> str:
        # append the version tag if not already present
        version = "v0." + version.lstrip("v0.")

        # check if all three parts / digits are present or not (major.minor.patch) => v0.4.24
        if version.count('.') != 2:
            raise ValueError(
                "Invalid solc version '{}' - must be in the format v0.x.x".format(version))

        # validate if the minimum version is supported or not
        # minimum version is v0.4.11
        v = [int(i) for i in version[1:].split('.')]
        if v[1] < 4 or (v[1] == 4 and v[2] < 11):
            raise ValueError(
                "py-solc-x does not support solc versions <0.4.11")
        return version

    @classmethod
    def _compare_versions(cls, available_version: str, given_version: str, comp='=') -> bool:
        # remove the version prefix
        available_version = available_version.lstrip('v')
        given_version = given_version.lstrip('v')

        # split into individual numbers of the version
        v1_split = [int(i) for i in available_version.split('.')]
        v2_split = [int(i) for i in given_version.split('.')]

        # base case, if need to check if equal or not
        if comp in ('=', '==', '', None):
            return v1_split == v2_split

        # base case, if comparison operator supplied is invalid or not
        if comp not in SolcSelector.operator_map:
            raise ValueError("operator {} not supported".format(comp))

        # base case, if ^ operator is used, is the 0th (major) and 1st (minor) digits mismatch
        # in this case the 3rd (patch) digit needs to be greater than or equal to
        # (however, we do not compare the 3rd digit, since we start from the latest version to the oldest v0.8.14 -> v0.4.11)
        # idx stores the index of the digit which mismatch (major / minor / patch)
        idx = next((i for i in range(3) if v1_split[i] != v2_split[i]), 2)
        if comp == '^' and idx != 2:
            return False

        # final case, compare using the operator provided as function params
        return SolcSelector.operator_map[comp](v1_split[idx], v2_split[idx])
