# -*- coding: utf-8 -*-

"""Main module."""

import logging
import contextlib

_LOGGER = logging.getLogger(__name__)

class LandroidMower:
    def __init__(self, username, password, on_message):
        import paho.mqtt.client as mqtt

        self.mqtt_client_id = ''
        self.endpoint = ''
        self.on_message = on_message

        self.api = LandroidApi()
        self.authenticate(username, password)
        self.get_mac_address()

        self.mqttc = mqtt.Client(self.mqtt_client_id, protocol=mqtt.MQTTv311)
        self.mqttc.enable_logger(logger=_LOGGER)

        self.mqttc.on_message = self.forward_on_message
        self.mqttc.on_connect = self.on_connect
        with self.get_cert() as cert:
            self.mqttc.tls_set(certfile=cert)

        connect_result = self.mqttc.connect(self.endpoint, port=8883, keepalive=600)
        if (connect_result):
            _LOGGER.error('Error connecting to MQTT: %s', error)

        self.mqttc.loop_start()

    #API Calls
    def authenticate(self, username, password):
        auth_data = self.api.auth(username, password)
        self.api.set_token(auth_data['api_token'])
        self.mqtt_client_id = auth_data['mqtt_client_id']
        self.endpoint = auth_data['mqtt_endpoint']

    @contextlib.contextmanager
    def get_cert(self):
        import base64

        certresp = self.api.get_cert()
        cert = base64.b64decode(certresp['pkcs12'])

        with pfx_to_pem(certresp['pkcs12']) as pem_cert:
            yield pem_cert

    def get_mac_address(self):
        products = self.api.get_products()
        self.mac_address = products[0]["mac_address"] #TODO: support for multiple devices?

    # MQTT callbacks
    def forward_on_message(self, client, userdata, message):
        import json

        json_message = message.payload.decode('utf-8')
        _LOGGER.debug("Received message '" + json_message
                      + "' on topic '" + message.topic
                      + "' with QoS " + str(message.qos))

        try:
            self.on_message(json.loads(json_message))
        except json.decoder.JSONDecodeError as e:
            import sys
            _LOGGER.error('Decoding JSON has failed')
            _LOGGER.error(sys.exc_info()[0])

    def on_connect(self, client, userdata, flags, rc):
        client.subscribe('DB510/' + self.mac_address + '/commandOut')

    # Mower functionality
    def start_mowing(self):
        self.mqttc.publish('DB510/' + self.mac_address + '/commandIn', '{"cmd":1}', qos=0, retain=False)

    def pause_mowing(self):
        self.mqttc.publish('DB510/' + self.mac_address + '/commandIn', '{"cmd":2}', qos=0, retain=False)

    def return_home(self):
        self.mqttc.publish('DB510/' + self.mac_address + '/commandIn', '{"cmd":3}', qos=0, retain=False)

    def disconnect(self):
        self.mqttc.disconnect()


@contextlib.contextmanager
def pfx_to_pem(pfx_data):
    ''' Decrypts the .pfx file to be used with requests.'''
    '''Based on https://gist.github.com/erikbern/756b1d8df2d1487497d29b90e81f8068'''
    import base64
    import OpenSSL.crypto
    import tempfile

    with tempfile.NamedTemporaryFile(suffix='.pem') as t_pem:
        f_pem = open(t_pem.name, 'wb')
        p12 = OpenSSL.crypto.load_pkcs12(base64.b64decode(pfx_data), '')
        f_pem.write(OpenSSL.crypto.dump_privatekey(OpenSSL.crypto.FILETYPE_PEM, p12.get_privatekey()))
        f_pem.write(OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, p12.get_certificate()))
        ca = p12.get_ca_certificates()
        if ca is not None:
            for cert in ca:
                f_pem.write(OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, cert))
        f_pem.close()
        yield t_pem.name

class LandroidApi:
    WORX_API_BASE = "https://api.worxlandroid.com/api/v1"

    def __init__(self):
        self.token = 'qiJNz3waS4I99FPvTaPt2C2R46WXYdhw'

    def set_token(self, token):
        self.token = token

    def get_headers(self):
        header_data = {}
        header_data['Content-Type'] = 'application/json'
        header_data['X-Auth-Token'] = self.token

        return header_data

    def auth(self, username, password, platform='android', type='app'):
        import uuid
        import json

        payload_data = {}
        payload_data['email'] = username
        payload_data['password'] = password
        payload_data['platform'] = platform
        payload_data['type'] = type
        payload_data['uuid'] = str(uuid.uuid1())

        payload = json.dumps(payload_data)

        return self.call('/users/auth', payload)

    def get_cert(self):
        return self.call('/users/certificate')

    def get_products(self):
        return self.call('/product-items')

    def call(self, path, payload=None):
        import requests

        if payload:
            req = requests.post(self.WORX_API_BASE + path, data=payload, headers=self.get_headers())
        else:
            req = requests.get(self.WORX_API_BASE + path, headers=self.get_headers())

        if not req.ok:
            _LOGGER.error("Error when calling Worx Landroid API. Status Code %s", req.status_code)

            return False

        return req.json()