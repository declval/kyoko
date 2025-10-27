#!/usr/bin/env python3

import argparse
import base64
import json
import os
import pathlib
import re
import secrets
import sys

from uuid import uuid4

PROGRAM = pathlib.Path(__file__).name
BASE_DIR = pathlib.Path(__file__).parent.parent
CADDY_CONFIG_PATH = BASE_DIR / 'caddy' / 'Caddyfile'
USERS_CONFIG_PATH = BASE_DIR / 'users.json'
XRAY_CONFIG_PATH = BASE_DIR / 'xray' / 'config.json'


class UsersConfig:
    def __init__(self):
        with open(USERS_CONFIG_PATH) as file:
            self.__config = json.loads(file.read())

    def __delitem__(self, uuid):
        del self.__config[uuid]

        self.save()

    def __getitem__(self, uuid):
        return self.__config[uuid]

    def __setitem__(self, uuid, username):
        self.__config[uuid] = username

        self.save()

    def save(self):
        with open(USERS_CONFIG_PATH, mode='w') as file:
            file.write(json.dumps(self.__config, indent=4, sort_keys=True))
            file.write('\n')


class XrayConfig:
    def __init__(self):
        with open(XRAY_CONFIG_PATH) as file:
            self.__config = json.loads(file.read())
            self.__clients = self.__config['inbounds'][0]['settings']['clients']
            self.__stream_settings = self.__config['inbounds'][0]['streamSettings']
            self.network = self.__stream_settings['network']

    def add(self):
        uuid = str(uuid4())

        self.__clients.append({'id': uuid})

        self.save()

        return uuid

    def count(self):
        return len(self.__clients)

    def get(self, number):
        try:
            client = self.__clients[number - 1]
        except IndexError:
            print('No client with that sequence number.', file=sys.stderr)
            return None

        return client['id']

    def list(self):
        users_config = UsersConfig()

        print('#\tName\t\tUUID')

        for i, client in enumerate(self.__clients, 1):
            uuid = client['id']
            print(f'{i}\t{users_config[uuid]}\t\t{uuid}')

    def path(self):
        match self.network:
            case 'ws':
                return self.__stream_settings['wsSettings']['path']
            case 'xhttp':
                return self.__stream_settings['xhttpSettings']['path']

    def remove(self, number):
        uuid = None

        try:
            uuid = self.__clients[number - 1]['id']
            del self.__clients[number - 1]
        except IndexError:
            print('No client with that sequence number.', file=sys.stderr)
            return None

        self.save()

        return uuid

    def save(self):
        with open(XRAY_CONFIG_PATH, mode='w') as file:
            file.write(json.dumps(self.__config, indent=4, sort_keys=True))
            file.write('\n')


def client(args):
    if (
        not CADDY_CONFIG_PATH.exists()
        or not USERS_CONFIG_PATH.exists()
        or not XRAY_CONFIG_PATH.exists()
    ):
        print(
            f'Necessary config files do not exist. Generate them with {PROGRAM} generate.',
            file=sys.stderr,
        )
        return

    users_config = UsersConfig()
    xray_config = XrayConfig()

    match args.action:
        case 'add':
            uuid = xray_config.add()

            username = input(
                'What should I call this user (Enter the username and press Enter)? '
            )

            users_config[uuid] = username
        case 'list':
            xray_config.list()
        case 'remove':
            if xray_config.count() == 0:
                print('No clients defined.', file=sys.stderr)
                return

            xray_config.list()

            number = input(
                'Which client to remove (Enter the sequence number and press Enter)? '
            )

            try:
                number = int(number)

                if number < 1:
                    raise ValueError
            except ValueError:
                print('Not a valid sequence number.', file=sys.stderr)
                return

            uuid = xray_config.remove(number)

            if uuid is None:
                return

            del users_config[uuid]


def connstr(args):
    if not CADDY_CONFIG_PATH.exists() or not XRAY_CONFIG_PATH.exists():
        print(
            f'Necessary config files do not exist. Generate them with {PROGRAM} generate.',
            file=sys.stderr,
        )
        return

    with open(CADDY_CONFIG_PATH) as file:
        config = file.read()
        res = re.search(r'^(?P<domain>.+) \{[\w\W]*\}', config, re.MULTILINE)
        domain = res.group('domain')

    xray_config = XrayConfig()

    if xray_config.count() == 0:
        print(
            f'No clients defined. Add one with {PROGRAM} client add.', file=sys.stderr
        )
        return

    if args.uuid is None:
        xray_config.list()

        number = input(
            'Which client to create a connection string for (Enter the sequence number and press Enter)? '
        )

        try:
            number = int(number)

            if number < 1:
                raise ValueError
        except ValueError:
            print('Not a valid sequence number.', file=sys.stderr)
            return

        args.uuid = xray_config.get(number)

        if args.uuid is None:
            return

    params = {
        'add': domain,
        'aid': '0',
        'host': domain,
        'id': args.uuid,
        'net': xray_config.network,
        'path': xray_config.path(),
        'port': '443',
        'ps': domain,
        'tls': 'tls',
        'type': 'none',
        'v': '2',
    }

    params = json.dumps(params)

    print(f'vmess://{base64.b64encode(params.encode()).decode()}')


def generate(args):
    path = f'/{secrets.token_urlsafe()}'

    # Generate a Caddy config
    with open(BASE_DIR / 'templates' / args.transport / 'Caddyfile') as file:
        caddy_config = file.read()

    os.makedirs(CADDY_CONFIG_PATH.parent, exist_ok=True)

    with open(CADDY_CONFIG_PATH, mode='w') as file:
        file.write(caddy_config.format(domain=args.domain, path=path))

    # Generate a users config
    os.makedirs(USERS_CONFIG_PATH.parent, exist_ok=True)

    with open(USERS_CONFIG_PATH, mode='w') as file:
        file.write('{}\n')

    # Generate an Xray config
    with open(BASE_DIR / 'templates' / args.transport / 'config.json') as file:
        xray_config = file.read()

    os.makedirs(XRAY_CONFIG_PATH.parent, exist_ok=True)

    with open(XRAY_CONFIG_PATH, mode='w') as file:
        file.write(xray_config.format(path=path))


parser = argparse.ArgumentParser(
    description='A tool to manage Caddy and Xray configs', prog=PROGRAM
)

subparsers = parser.add_subparsers(required=True)

client_parser = subparsers.add_parser('client', help='Add, list or remove clients')
client_parser.add_argument('action', choices=('add', 'list', 'remove'))
client_parser.set_defaults(func=client)

connstr_parser = subparsers.add_parser(
    'connstr', help='Create a connection string for a client'
)
connstr_parser.add_argument('-u', '--uuid')
connstr_parser.set_defaults(func=connstr)

generate_parser = subparsers.add_parser(
    'generate', help='Generate Caddy, users and Xray configs'
)
generate_parser.add_argument('-d', '--domain', default='localhost')
generate_parser.add_argument(
    '-t', '--transport', choices=('ws', 'xhttp'), default='xhttp'
)
generate_parser.set_defaults(func=generate)

args = parser.parse_args()

args.func(args)
