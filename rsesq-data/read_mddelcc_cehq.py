# -*- coding: utf-8 -*-
"""
Created on Tue Jun 13 14:29:29 2017
@author: jnsebgosselin
"""

# ---- Imports: standard library

import urllib
from urllib.request import urlopen, urlretrieve
from urllib.error import HTTPError, URLError
from io import BytesIO
import numpy as np
import re
import os
import requests
import csv
import datetime
from multiprocessing import Pool

# ---- Imports: third parties

from bs4 import BeautifulSoup
from xlrd.xldate import xldate_from_date_tuple

# ---- Imports: local

from base import AbstractReader


# ---- Utilities

ACTIVE_STATION_LIST = [
        '010802', '010902', '011003', '011204', '011508', '011509', '011707',
        '020404', '020602', '021407', '021601', '021605', '021702', '021916',
        '022003', '022301', '022501', '022505', '022507', '022513', '022601',
        '022704', '023002', '023004', '023106', '023303', '023401', '023402',
        '023409', '023422', '023427', '023429', '023432', '023446', '023702',
        '024003', '024014', '024015', '024016', '030101', '030103', '030106',
        '030118', '030201', '030202', '030208', '030215', '030220', '030225',
        '030234', '030241', '030247', '030268', '030278', '030282', '030283',
        '030284', '030289', '030296', '030297', '030298', '030299', '030302',
        '030304', '030309', '030314', '030316', '030326', '030332', '030340',
        '030342', '030343', '030345', '030348', '030350', '030353', '030415',
        '030421', '030423', '030424', '030425', '030426', '030429', '030430',
        '030905', '030907', '030919', '030920', '030921', '040101', '040102',
        '040103', '040104', '040105', '040106', '040107', '040108', '040109',
        '040110', '040122', '040129', '040132', '040204', '040212', '040238',
        '040239', '040406', '040409', '040602', '040605', '040608', '040609',
        '040619', '040624', '040627', '040629', '040829', '040830', '040840',
        '040841', '041902', '042609', '042610', '042611', '043003', '043004',
        '043005', '043012', '043030', '043031', '043108', '043205', '043206',
        '043208', '043301', '046709', '048603', '050119', '050135', '050144',
        '050147', '050304', '050408', '050409', '050501', '050702', '050801',
        '050805', '050807', '050812', '050813', '050904', '050915', '050916',
        '051001', '051002', '051003', '051004', '051005', '051007', '051502',
        '052212', '052219', '052228', '052233', '052235', '052401', '052601',
        '052603', '052604', '052606', '052805', '054001', '060102', '060704',
        '060901', '061001', '061002', '061004', '061020', '061022', '061024',
        '061028', '061029', '061307', '061502', '061601', '061602', '061801',
        '061901', '061909', '062002', '062102', '062114', '062701', '062803',
        '062914', '064101', '070204', '071203', '071401', '071801', '072301',
        '073503', '074903', '075705', '076601', '080101', '080106', '080707',
        '080718', '080809', '081101', '089902', '089903', '089907', '093801',
        '095003', '102706', '103605', '103702', '104001', '104803', '120201']


def dms2decdeg(coord):
    """
    Convert decimal, minute, second format lat/lon coordinate to
    decimal degree.
    """
    sign = np.sign(coord[0])
    dd = abs(coord[0]) + coord[1]/60 + coord[2]/3600
    return sign*dd


def findUnique(pattern, string):
    """
    Return the first result found for the regex search or return None if
    nothing is found.
    """
    result = re.findall(pattern, string)
    if len(result) > 0:
        return result[0].strip()
    else:
        return None


def find_float_from_str(string, sep):
    """
    Search a string to find a float number if any.
    """
    float_ = ''
    digit_sep_found = False
    for char in string:
        if char.isdigit():
            float_ += char
        else:
            if char == sep and not digit_sep_found:
                digit_sep_found = True
                float_ += '.'
    return float(float_)


def format_url_to_ascii(url):
    """
    Convert non_ASCII char in the url if any.
    """
    url = urllib.parse.urlsplit(url)
    url = list(url)
    url[2] = urllib.parse.quote(url[2])
    url = urllib.parse.urlunsplit(url)
    return url


# ---- Base functions

def read_html_from_url(url):
    """"Get, read and decode html data from a url in the the CEHQ domain."""
    try:
        html = urlopen(url).read()
    except (HTTPError, URLError):
        return None

    try:
        data = html.decode('iso-8859-1').split('\r\n')
        return data
    except (UnicodeDecodeError, UnicodeError):
        return None


def scrape_station_ids():
    """
    Get a list of the IDs of all the stations for which data are available
    on the CEHQ website
    """
    url = ("http://www.cehq.gouv.qc.ca/hydrometrie/"
           "historique_donnees/default.asp")

    soup = BeautifulSoup(urlopen(url), 'html.parser')
    select = soup.find("select", attrs={"id": "lstStation"})
    options = select.find_all("option")

    return [row.text.strip() for row in options if row.text.strip()]


def scrape_station_datasheet(sid):
    """
    Read the information in the station datasheet.
    """
    url = "http://www.cehq.gouv.qc.ca/hydrometrie/historique_donnees/"
    url += "fiche_station.asp?NoStation=%s" % sid
    html = urlopen(url).read().decode('iso-8859-1')

    FIELDS_KEYS = [('Numéro de la station :', 'ID'),
                   ('Nom de la station :', 'Name'),
                   ('Description :', 'Description'),
                   ('État :', 'Status'),
                   ("Période(s) d'activité :", 'Active period'),
                   ("Municipalité :", 'Municipality'),
                   ('Région administrative :', 'Administrative Region'),
                   ("Lac ou cours d'eau :", 'Stream Name'),
                   ("Région hydrographique", 'Hydrographic Region'),
                   ("Bassin versant à la station", 'Drainage Area'),
                   ("Régime d'écoulement", 'Flow Regime'),
                   ("Numéro fédéral de la station :", "Federal ID")]

    # BeautifulSoup is not working correctly for this content due to the mixed
    # up of <a> and <b> fields in the table. So we use a basic crawling of the
    # content using regexes instead.

    data = {}
    for field, key in FIELDS_KEYS:
        idx = html.find(field)
        data[key] = findUnique('<td width="421">(.*?)&nbsp;</td>', html[idx:])

    data['Active period'] = data['Active period'].replace('<br>', ' ; ')

    data['Drainage Area'] = data['Drainage Area'].replace(',', '.')
    data['Drainage Area'] = data['Drainage Area'].replace(' km²', '')
    data['Drainage Area'] = data['Drainage Area'].replace('\xa0', '')
    try:
        data['Drainage Area'] = float(data['Drainage Area'])
    except ValueError:
        data['Drainage Area'] = 'Non disponible'

    return data


def scrape_station_data_header(data):
    """
    Get latitude, longitude, and elevation (if available) from the header of
    the datafile.
    """
    df = {}

    # ---- Scrape latitude and longitude

    items = [item[:-1] for item in data[4].split()]
    df['Latitude'] = dms2decdeg((int(items[2]), int(items[3]), int(items[4])))
    df['Longitude'] = dms2decdeg((int(items[6]), int(items[7]), int(items[8])))

    # ---- Scrape elevation if available

    items = [s.strip() for s in data[5].split() if s]
    try:
        df['Elevation'] = float(items[2])
    except (IndexError, ValueError):
        df['Elevation'] = 'Non disponible'

    return df


def scrape_daily_series_from_txt(sid, data):
    """
    Structured the daily streamflow and level that were downloaded on the CEHQ
    website into structured arrays and store them in a dataframe.
    """
    df = {'Time': [], 'Year': [], 'Month': [], 'Day': [],
          'Daily values': [], 'Note': []}

    if data is None:
        return df
    else:
        for row in data:
            row = [s.strip() for s in row.split()]
            try:
                if row[0] == sid:
                    date = [int(s) for s in row[1].split("/")]
                    df['Time'].append(xldate_from_date_tuple(date, 0))
                    df['Year'].append(date[0])
                    df['Month'].append(date[1])
                    df['Day'].append(date[2])
                    try:
                        df['Daily values'].append(float(row[2]))
                    except IndexError:
                        df['Daily values'].append(np.nan)
                    try:
                        df['Note'].append(row[3])
                    except IndexError:
                        df['Note'].append('')
            except IndexError:
                pass
        return df


def scrape_data_from_sid(sid):
    """
    This is a meta function that will read and restructured station info and
    daily streamflow and level data for the station with the specified id.
    """
    df_dly_hydat = {'ID': sid}

    root = "http://www.cehq.gouv.qc.ca/depot/historique_donnees/"
    data_Q = read_html_from_url(root+"fichier/%s_Q.txt" % sid)
    data_N = read_html_from_url(root+"fichier/%s_N.txt" % sid)

    if data_N:
        df_dly_hydat.update(scrape_station_data_header(data_N))
    elif data_Q:
        df_dly_hydat.update(scrape_station_data_header(data_Q))
    else:
        return {}

    df_Q = scrape_daily_series_from_txt(sid, data_Q)
    df_N = scrape_daily_series_from_txt(sid, data_N)

    # ---- Combine flow and level datasets

    time = np.hstack([df_Q['Time'], df_N['Time']])
    time = np.unique(time)
    time = np.sort(time)

    df_dly_hydat['Time'] = time
    for field in ['Year', 'Month', 'Day']:
        df_dly_hydat[field] = np.zeros(len(time)).astype(int)
    for field in ['Flow', 'Level']:
        df_dly_hydat[field] = np.zeros(len(time)).astype(float) * np.nan

    indexes = np.digitize(df_Q['Time'], time, right=True)
    for key in ['Year', 'Month', 'Day']:
        df_dly_hydat[key][indexes] = df_Q[key]
    df_dly_hydat['Flow'][indexes] = df_Q['Daily values']

    indexes = np.digitize(df_N['Time'], time, right=True)
    for key in ['Year', 'Month', 'Day']:
        df_dly_hydat[key][indexes] = df_N[key]
    df_dly_hydat['Level'][indexes] = df_N['Daily values']

    return df_dly_hydat


def fetch_station_data(sid):
    df = {'ID': sid}
    df.update(scrape_station_datasheet(sid))
    df.update(scrape_data_from_sid(sid))
    return df


# ---- API


class MDDELCC_CEHQ_Reader(AbstractReader):
    DATABASE_FILEPATH = 'mddelcc_cehq_stations.npy'

    def __init__(self):
        super(MDDELCC_CEHQ_Reader, self).__init__()

    def stations(self):
        return self._db.values()

    def station_ids(self):
        return list(self._db.keys())

    def load_database(self):
        try:
            self._db = np.load(self.DATABASE_FILEPATH).item()
        except FileNotFoundError:
            self.fetch_database_from_mddelcc()

    def fetch_database_from_mddelcc(self):
        sids = scrape_station_ids()
        self._db = {}
        p = Pool(5)
        itr = 0
        for result in p.imap(fetch_station_data, sids):
            itr += 1
            args = (result['ID'], itr, len(sids))
            print('Data for station %s fetched: %d of %d' % args, end="\r")
            self._db[result['ID']] = result
        print()
        p.close()
        p.join()
        np.save(self.DATABASE_FILEPATH, self._db)

    def fetch_station_data(self, sid):
        self._db[sid] = fetch_station_data(sid)
        np.save(self.DATABASE_FILEPATH, self._db)
        return self._db[sid]

    def save_station_to_hdf5(self):
        pass

    def save_station_to_csv(self, sid, filepath):
        """
        Save data from local database to csv. If the data are not already
        saved in the local database, it is fetched from the mddelcc website.
        """
        if len(self._db[sid]) == 0:
            self.fetch_station_data(sid)
        station = self._db[sid]

        # Generate the file header.
        fc = [['Station ID', station['ID']],
              ['Station Name', station['Name']],
              ['Description', station['Description']],
              ['Status', station['Status']],
              ['Active period', station['Active period']],
              ['Province', 'Qc'],
              ['Municipality', station['Municipality']],
              ['Administrative Region', station['Administrative Region']],
              ['Stream Name', station['Stream Name']],
              ['Hydrographic Region', station['Hydrographic Region']],
              ['Latitude (dd)', station['Latitude']],
              ['Longitude (dd)', station['Longitude']],
              ['Elevation (m)', station['Elevation']],
              ['Drainage Area (km2)', station['Drainage Area']],
              ['Flow Regime', station['Flow Regime']],
              [],
              ['Source', 'https://www.cehq.gouv.qc.ca'],
              ['Federal ID', station["Federal ID"]],
              [],
              ['Time', 'Year', 'Month', 'Day', 'Level (m)', 'Flow (m3/s)']]

        # Append the dataset.
        data = np.vstack([station['Time'], station['Year'], station['Month'],
                          station['Day'], station['Level'], station['Flow']]
                         ).transpose().tolist()
        fc.extend(data)

        # Create the destination directory if it doesn't exist.
        filepath = os.path.abspath(filepath)
        if not os.path.exists(os.path.dirname(filepath)):
            os.makedirs(os.path.dirname(filepath))

        # Save the csv.
        with open(filepath, 'w', encoding='iso-8859-1') as f:
            writer = csv.writer(f, delimiter=',', lineterminator='\n')
            writer.writerows(fc)


if __name__ == "__main__":
    reader = MDDELCC_CEHQ_Reader()
    reader.fetch_database_from_mddelcc()