#!/usr/bin/python3

from __future__ import absolute_import, unicode_literals
import gevent.monkey
gevent.monkey.patch_all(thread=False, select=False)
from requests.packages.urllib3.util.ssl_ import create_urllib3_context
create_urllib3_context()

from configparser import ConfigParser
import requests
import grequests
import json
import os
import re
from pprint import pprint
from datetime import datetime
import humanize
import random
import csv

import random


class OdooSessionExpired(Exception):
    """raised when session is expired"""
    pass


class OdooError(Exception):
    """raised when odoo has trouble or got an error"""
    pass


class RPC(object):
    def __init__(self, url, db, user, password):
        self._payload = {'id': random.randint(0, 1000000000), 'jsonrpc': '2.0', 'method': 'call', 'params': {}}
        self._headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        self._base_path = 'web/dataset/call_kw'
        self._url, self._db, self._user, self._password, self._session = url, db, user, password, {}

    def async_post(self, path, payload, count=0):
        url = '/'.join([self._url, path])
        if self._session:
            ret = grequests.post(url, verify=False, data=json.dumps(payload), headers=self._headers, 
                                     cookies=dict(session_id=self._session.get('session_id', None)), timeout=1)
        else:
            s = requests.Session()
            s.headers.update(self._headers)
            ret = grequests.post(url, verify=False, data=json.dumps(payload), headers=self._headers, session=s, timeout=1)
        return ret

    def post(self, path, payload, count=0):
        url = '/'.join([self._url, path])
        if self._session:
            res = requests.post(url=url, data=json.dumps(payload), headers=self._headers,
                            cookies=dict(session_id=self._session.get('session_id', None)), timeout=None, verify=False)
        else:
            s = requests.Session()
            s.headers.update(self._headers)
            res = s.post(url=url, data=json.dumps(payload), headers=self._headers, timeout=None, verify=False)
            self._session.update({'session_id': s.cookies.get('session_id')})
        if res.status_code == 502:
            print('BAD GATEWAY')
            return {}
        else:
            res = res.json()
        if 'result' in res:
            return {'data': res['result']}
        elif 'error' in res:
            if res['error']['data']['message'] == 'Session expired':
                count += 1
                if count > 3:
                    raise OdooError('login failed, maybe wrong user or password')
                self.login()
                return self.post(path, payload, count)
            else:
                pprint(res['error'])
                raise OdooError(res['error']['data']['message'])
        return {}

    def call(self, model, method, args, kwargs):
        params = {'model': model, 'method': method, 'args': args, 'kwargs': kwargs}
        path = '/'.join([self._base_path, model, method])
        payload = dict(self._payload, params=params)
        result = self.post(path=path, payload=payload)
        if 'error' in result:
            return result
        return result.get('data', [])

    def async_call(self, model, method, args, kwargs):
        params = {'model': model, 'method': method, 'args': args, 'kwargs': kwargs}
        path = '/'.join([self._base_path, model, method])
        payload = dict(self._payload, params=params)
        result = self.async_post(path=path, payload=payload)
        return result

    def login(self):
        path = 'web/session/authenticate'
        params = {'db': self._db, 'login': self._user, 'password': self._password}
        payload = dict(self._payload, params=params)
        result = self.post(path=path, payload=payload).get('data', [])

    def search(self, model, domain, context=None, method='search'):
        kwargs = {}
        if context:
            kwargs['context'] = context
        return self.call(model=model, method=method, args=[domain], kwargs=kwargs)

    def read(self, model, ids, fields, context=None, method='read'):
        kwargs = {'fields': fields}
        if context:
            kwargs['context'] = context
        return self.call(model=model, method=method, args=[ids], kwargs=kwargs)

    def search_read(self, model, domain, fields, context=None, limit=None, method='search_read'):
        kwargs = {'fields': fields}
        if isinstance(limit, int):
            kwargs['limit'] = limit
        if context:
            kwargs['context'] = context
        return self.call(model=model, method=method, args=[domain], kwargs=kwargs)

    def async_search(self, model, domain, context=None, limit=None, method='search'):
        kwargs = {}
        if isinstance(limit, int):
            kwargs['limit'] = limit
        if context:
            kwargs['context'] = context
        return self.async_call(model=model, method=method, args=[domain], kwargs=kwargs)

    def async_read(self, model, ids, fields, context=None, limit=None, method='read'):
        kwargs = {'fields': fields}
        if isinstance(limit, int):
            kwargs['limit'] = limit
        if context:
            kwargs['context'] = context
        return self.async_call(model=model, method=method, args=[ids], kwargs=kwargs)

    def async_search_read(self, model, domain, fields, context=None, limit=None, method='search_read'):
        kwargs = {'fields': fields}
        if isinstance(limit, int):
            kwargs['limit'] = limit
        if context:
            kwargs['context'] = context
        return self.async_call(model=model, method=method, args=[domain], kwargs=kwargs)

    def create(self, model, values, context=None, method='create'):
        if context is None:
            context = {}
        return self.call(model=model, method=method, args=[values], kwargs=context)

    def async_create(self, model, values, context=None, method='create'):
        if context is None:
            context = {}
        return self.async_call(model=model, method=method, args=[values], kwargs=context)

    def write(self, model, ids, values, method='write'):
        return self.call(model=model, method=method, args=[ids, values], kwargs={})
    
    def async_write(self, model, ids, values, method='write'):
        return self.async_call(model=model, method=method, args=[ids, values], kwargs={})


class Environment(RPC):
    def __init__(self, env=None, url=None):
        if not env:
            raise Exception('Cannot run without environment declaration')
        #print('environment: ', env.upper())
        config = ConfigParser()
        config_path = os.path.join(os.path.dirname(__file__), 'config.cfg')
        config.read(config_path)
        config = config[env.upper()]
        self.config = config
        if not url:
            url = config['url']
        RPC.__init__(self, url=url, db=config['db'], user=config['user'], password=config['password'])
        self.login()

    def populate_product(self):
        f = open('data.csv', 'r')
        reader = csv.reader(f)
        first = True
        for line in reader:
            if first:
                first = False
                continue
            name = line[1]
            price = line[4]
            code = line[5]
            d = {
                'name': name,
                'list_price': price,
                'default_code': code,
                'type': 'product'
            }
            self.create('product.template', d)
        f.close()

    def populate_contact(self, is_customer_rank=False):
        f = open('customer.csv', 'r')
        reader = csv.reader(f)
        first = True
        for line in reader:
            if first:
                first = False
                continue
            name = line[0]
            code = line[1]
            d = {
                'name': name,
                'ref': code
            }
            if is_customer_rank:
                d.update({'customer_rank': 1, 'supplier_rank': 1})
            else:
                d.update({'customer': True, 'supplier': True})
            self.create('res.partner', d)


if __name__ == '__main__':
    envs = [
        'O11',
        'O12',
        'O13',
        'O14',
        'O15'
    ]
    deactivate_cron = True
    create_data_master = True
    create_po = True
    confirm_po = True
    validate_do = True
    create_vb = True
    validate_vb = True
    d_po = {}
    partner_ref = 'ABCDEF'
    
    if deactivate_cron:
        print('Deactivate cron')
        for xenv in envs:
            env = Environment(env=xenv)
            cron_ids = env.search_read('ir.cron', domain=[('active','=',True)], fields=['id'])
            if len(cron_ids) > 0:
                env.write('ir.cron', [i['id'] for i in cron_ids], {'active': False})
    
    if create_data_master:
        print('Create data master')
        for xenv in envs:
            env = Environment(env=xenv)
            start = datetime.now()
            env.populate_product()
            if xenv in ['O13','O14','O15']:
                env.populate_contact(is_customer_rank=True)
            else:
                env.populate_contact()
            end = datetime.now()
            delta = end - start
            print(xenv, delta, humanize.precisedelta(delta, minimum_unit='milliseconds', format='%d'))

    if create_po:
        print('Create PO')
        for xenv in envs:
            env = Environment(env=xenv)
            start = datetime.now()
            domain = [('type','=','product')]
            if xenv == 'O15':
                domain = [('detailed_type','=','product')]
            domain += [('default_code','in', [str(i).zfill(3) for i in range(1,71)])]
            products = env.search_read('product.product', domain=domain, fields=['id','name', 'list_price', 'type', 'uom_id', 'uom_po_id'])
            customers = env.search_read('res.partner', domain=[], fields=['id','name'])
            date_planned = datetime.today().strftime('%Y-%m-%d')
            start = datetime.now()
            for i in range(100):
                d = {
                    'partner_id': customers[0]['id'],
                    'partner_ref': partner_ref,
                    'order_line': []
                }
                for j in products:
                    d['order_line'].append((0, 0, {'product_id': j['id'], 'name': j['name'], 'date_planned': date_planned, 'product_uom': j['uom_po_id'][0], 'product_qty': 100, 'price_unit': j['list_price']}))
                result = env.create('purchase.order', d)
            end = datetime.now()
            delta = end - start
            print(xenv, delta, humanize.precisedelta(delta, minimum_unit='milliseconds', format='%d'))

    if confirm_po:
        print('Confirm PO')
        for xenv in envs:
            env = Environment(env=xenv)
            ids = env.search_read('purchase.order', domain=[('partner_ref','=',partner_ref),('state','=','draft')], fields=['id'])
            start = datetime.now()
            for i in ids:
                env.call(model='purchase.order', method='button_confirm', args=[i['id']], kwargs={})
            end = datetime.now()
            delta = end - start
            print(xenv, delta, humanize.precisedelta(delta, minimum_unit='milliseconds', format='%d'))

    if validate_do:
        print('Validate GRN')
        for xenv in envs:
            env = Environment(env=xenv)
            ids = env.search_read('purchase.order', domain=[('partner_ref','=',partner_ref)], fields=['id','picking_ids'])
            ids2 = env.search_read('stock.picking', domain=[('purchase_id','in',[i['id'] for i in ids])], fields=['id','purchase_id'])
            for i in ids2:
                ids3 = env.search_read('stock.move', domain=[('picking_id','=',i['id'])], fields=['id','product_uom_qty'])
                for j in ids3:
                    env.write('stock.move', [j['id']], {'quantity_done': j['product_uom_qty']})
            start = datetime.now()
            for i in ids2:
                env.call(model='stock.picking', method='button_validate', args=[i['id']], kwargs={})
            end = datetime.now()
            delta = end - start
            print(xenv, delta, humanize.precisedelta(delta, minimum_unit='milliseconds', format='%d'))

    if create_vb:
        print('Create VB')
        for xenv in envs:
            env = Environment(env=xenv)
            ids_journal = env.search_read('account.journal', domain=[('type','=','purchase')], fields=['id'])
            journal_id = ids_journal[0]['id']
            ids_user = env.search_read('res.users', domain=[('login','=',env._user)], fields=['id','partner_id'])
            user_id = ids_user[0]['id']
            ids_partner = env.search_read('res.partner', domain=[('id','=',ids_user[0]['partner_id'][0])], fields=['id','property_account_payable_id'])
            account_id = ids_partner[0]['property_account_payable_id'][0]
            ids = env.search_read('purchase.order', domain=[('partner_ref','=',partner_ref)], fields=['id','name','partner_ref','partner_id'])
            start = datetime.now()
            for i in ids:
                d = {
                    'state': 'draft',
                    'user_id': user_id,
                    'purchase_id': i['id'],
                    'partner_id': i['partner_id'][0],
                    'journal_id': journal_id,
                    'invoice_line_ids': []
                }
                d_categ = {}
                ids2 = env.search_read('purchase.order.line', domain=[('order_id','=',i['id'])], fields=['product_id','name','product_qty','price_unit'])
                for j in ids2:
                    product_id = j['product_id'][0]
                    ids_product = env.search_read('product.product', domain=[('id','=',product_id)], fields=['id','categ_id'])
                    if ids_product[0]['categ_id'][0] not in d_categ:
                        ids_categ = env.search_read('product.category', domain=[('id','=',ids_product[0]['categ_id'][0])], fields=['id','property_stock_account_input_categ_id'])
                        categ_id = ids_categ[0]['property_stock_account_input_categ_id'][0]
                        d_categ[ids_product[0]['categ_id'][0]] = categ_id
                    d2 = {
                        'product_id': product_id,
                        'name': j['name'],
                        'quantity': j['product_qty'],
                        'price_unit': j['price_unit'],
                        'purchase_line_id': j['id'],
                        'account_id': d_categ[ids_product[0]['categ_id'][0]]
                    }
                    if xenv in ['O13','O14','O15']:
                        d2.update({'exclude_from_invoice_tab': False})
                    d['invoice_line_ids'].append((0,0,d2))
                if xenv in ['O14','O15']:
                    d.update({'move_type': 'in_invoice', 'invoice_date': datetime.today().strftime('%Y-%m-%d')})
                else:
                    d.update({'type': 'in_invoice'})
                if xenv in ['O13','O14','O15']:
                    d.update({'ref': i['name']})
                    id = env.create('account.move', d)
                else:
                    d.update({'account_id': account_id, 'reference': i['name'], 'origin': i['name']})
                    id = env.create('account.invoice', d)
            end = datetime.now()
            delta = end - start
            print(xenv, delta, humanize.precisedelta(delta, minimum_unit='milliseconds', format='%d'))

    if validate_vb:
        print('Validate VB')
        for xenv in envs:
            env = Environment(env=xenv)
            ids = env.search_read('purchase.order', domain=[('partner_ref','=',partner_ref)], fields=['id','invoice_ids'])
            ids2 = [i['invoice_ids'][0] for i in ids]
            start = datetime.now()
            for i in ids2:
                if xenv in ['O13','O14','O15']:
                    env.call(model='account.move', method='action_post', args=[i], kwargs={})
                else:
                    env.call(model='account.invoice', method='action_invoice_open', args=[i], kwargs={})
            end = datetime.now()
            delta = end - start
            print(xenv, delta, humanize.precisedelta(delta, minimum_unit='milliseconds', format='%d'))


