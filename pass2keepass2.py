# TODO warning about lack of in-memory security

import os
import subprocess
from shutil import copyfile
from typing import List, Tuple, Dict

from pykeepass import PyKeePass
from pykeepass.entry import Entry

PassKeyCls = "PassKey"


class PassReader:
    """Read a pass db and construct an in-memory version of it."""

    keys: List[PassKeyCls]

    def __init__(self, path: str = None):
        """Constructor for PassReader

        :param path: optional password-store location.
            Default is '~/.password-store'.
        """
        self.keys = []
        if path is not None:
            self.path = os.path.abspath(os.path.expanduser(path))
            self.pass_cmd = ["env", "PASSWORD_STORE_DIR={}".format(self.path), "pass"]
        else:
            self.path = os.path.expanduser("~/.password-store")
            self.pass_cmd = ["pass"]

    def get_keys(self) -> List[str]:
        """Return the list of keys in the pass db."""
        keys = [os.path.join(dirpath, fn)[len(self.path):-4]
                for dirpath, dirnames, files in os.walk(self.path)
                for fn in files if fn.endswith('.gpg')]
        return keys

    def parse_key(self, key: str) -> PassKeyCls:
        """Return a parsed PassKey."""
        return PassKey(reader=self, key=key)

    def parse_db(self):
        """Populate the keys list with all the data from the pass db."""
        for key in self.get_keys():
            self.keys.append(self.parse_key(key))


class PassKey:
    """A simple pass key in-memory representation"""

    to_skip: List[str] = ["---", ""]  # these lines will be skipped when parsing

    groups: List[str]
    title: str
    password: str
    url: str
    user: str
    notes: str
    custom_properties: Dict[str, str]

    def __init__(self, reader: PassReader, key: str):
        """Constructor for PassKey.

        :param reader:  a PassReader instance, used to access the key
        :param key:  string representing the key name
        """
        self.url = ""
        self.user = ""
        self.notes = ""
        self.custom_properties = {}
        self.groups = self.get_groups(key)
        self.title = self.get_title(key)
        key_string = self.decrypt_key(reader, key)
        self.parse_key_string(key_string)

    @staticmethod
    def get_title(key: str) -> str:
        """Return the key title."""
        return key.split("/").pop()

    @staticmethod
    def get_groups(key: str) -> List[str]:
        """Return the key groups."""
        groups = key.split("/")
        groups.pop()
        groups.pop(0)
        return groups

    @staticmethod
    def decrypt_key(reader: PassReader, key: str) -> str:
        """Decrypt the key using pass and return it as a string."""
        return subprocess.check_output(reader.pass_cmd + ["show", key]).decode("UTF-8")

    @staticmethod
    def is_valid_line(key_line: str) -> bool:
        """Accept as valid only lines in the format of 'key: value'."""
        return key_line.find(":") > 0

    @staticmethod
    def parse_key_line(key_line: str) -> Tuple[str, str]:
        """Parse a line in the format 'key: value'."""
        data = key_line.split(":", 1)
        return data[0].strip(), data[1].strip()

    def parse_key_string(self, key_string: str) -> None:
        """Parse a key and extract all useful data."""
        lines = key_string.split("\n")
        self.password = lines.pop(0)

        lines = list(filter(lambda x: x not in self.to_skip and self.is_valid_line(x), lines))
        data = list(map(lambda x: self.parse_key_line(x), lines))
        for key, value in data:
            if key == "url":
                self.url = value
            elif key == "user":
                self.user = value
            elif key == "notes":
                self.notes = value
            else:
                self.custom_properties.update({key: value})


class DbAlreadyExistsException(Exception):
    """Trying to overwrite an already existing keepass db."""


class P2KP2:
    """Convert a Pass db into a Keepass2 one."""

    db: PyKeePass

    def __init__(self, password: str, destination: str = "pass.kdbx"):
        """Constructor for P2KP2

        :param password: the password for the new Keepass db
        :param destination: the final db path
        """
        if not os.path.exists(destination):
            copyfile("empty.kdbx", destination)
        else:
            raise DbAlreadyExistsException()
        self.db = PyKeePass(destination)
        self.db.password = password
        self.db.save()

    def add_key(self, key: PassKey) -> Entry:
        """Add a keepass entry to the db containing all data from the relative pass entry. Create the group if needed.

        :param key: the original pass entry
        :return: the newly added keepass entry
        """
        # find the correct group for the key. If not there, create it
        key_group = self.db.root_group  # start from the root group
        if len(key.groups) > 0:
            for group_name in key.groups:
                # since pass folder names are unique, the possible first result is also the only one
                group = self.db.find_groups(name=group_name, recursive=False, group=key_group, first=True)
                if group is None:
                    # the group is not already there, let's create it
                    group = self.db.add_group(destination_group=key_group, group_name=group_name)
                key_group = group
        # create the entry, setting group, title, user and pass
        entry = self.db.add_entry(key_group, key.title, key.user, key.password)
        # set the url and the notes
        entry.url = key.url
        entry.notes = key.notes
        # add all custom fields
        for key, value in key.custom_properties.items():
            entry.set_custom_property(key, value)
        return entry
