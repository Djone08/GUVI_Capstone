from functools import wraps
import pandas as pd
import streamlit as st
from typing import Literal, Callable
import sqlite3
import mysql.connector as db
from googleapiclient.discovery import build


class YTDataBase(object):
    def __init__(self, db_type: Literal['sqlite', 'mysql'] | None = 'sqlite', host: str | None = None,
                 user: str | None = None, password: str | None = None, port: int | None = None,
                 schema: str | None = None, data_base_path: str | None = None):
        self.db_type = db_type

        if self.db_type == 'mysql':
            self.db = db.connect(host=host, user=user, password=password, port=port)
        elif self.db_type == 'sqlite':
            self.data_base = data_base_path or 'database.db'
            self.db = sqlite3.connect(self.data_base)

        self.cur = self.db.cursor()
        if self.db_type == 'mysql':
            self.cur.execute(f'create database if not exists {schema}')
            self.cur.execute(f'use {schema}')
        self.cur.close()

        self.set_tables()

    @staticmethod
    def with_cursor(func: Callable) -> Callable:
        @wraps(func)
        def wrapper_func(self, *args, **kwargs):
            if self.db_type == 'sqlite':
                self.db = sqlite3.connect(self.data_base)
            self.cur = self.db.cursor()
            if self.db_type == 'sqlite':
                self.cur.execute('pragma foreign_keys = 1')
            value = func(self, *args, **kwargs)
            self.cur.close()
            if self.db_type == 'sqlite':
                self.db.close()
            return value
        return wrapper_func

    @with_cursor
    def set_tables(self):
        self.cur.execute('''create table if not exists channels(
                id varchar(255) not null,
                thumbnails varchar(255),
                title varchar(255),
                description text,
                viewCount bigint,
                subscriberCount bigint,
                videoCount int,
                primary key (id))''')

        self.cur.execute('''create table if not exists playlists(
                id varchar(255) not null,
                channelId varchar(255),
                thumbnails varchar(255),
                title varchar(255),
                description text,
                publishedAt datetime,
                itemCount int,
                constraint playlists_channelId_fk foreign key (channelId)
                references channels(id) on update restrict on delete cascade,
                primary key (id))''')

        self.cur.execute('''create table if not exists videos(
                id varchar(255) not null,
                channelId varchar(255),
                playlistId varchar(255),
                thumbnails varchar(255),
                title varchar(255),
                description text,
                publishedAt datetime,
                duration time,
                viewCount bigint,
                likeCount bigint,
                dislikeCount bigint,
                commentCount bigint,
                constraint videos_channelId_fk foreign key (channelId)
                references channels(id) on update restrict on delete cascade,
                constraint videos_playlistId_fk foreign key (playlistId)
                references playlists(id) on update restrict on delete cascade,
                primary key (id))''')

        self.cur.execute('''create table if not exists comments(
                id varchar(255) not null,
                channelId varchar(255),
                videoId varchar(255),
                authorProfileImage varchar(255),
                textDisplay text,
                textOriginal text,
                likeCount int,
                publishedAt datetime,
                updatedAt datetime,
                constraint comments_channelId_fk foreign key (channelId)
                references channels(id) on update restrict on delete cascade,
                constraint comments_videoId_fk foreign key (videoId)
                references videos(id) on update restrict on delete cascade,
                primary key (id))''')

    def insert_data(self, _table_name: str, **kwargs):
        _data = tuple(x for x in kwargs.values())
        _cols = ','.join(x for x in kwargs)
        if self.db_type == 'sqlite':
            _data_filler = ('?,' * len(_data))[:-1]
            self.cur.execute(f'insert into {_table_name} ({_cols}) values ({_data_filler})', _data)
        elif self.db_type == 'mysql':
            self.cur.execute(f'insert into {_table_name} ({_cols}) values {_data}')
        self.db.commit()

    def update_data(self, _table_name: str, **kwargs):
        if self.db_type == 'sqlite':
            _data = list(kwargs.values())
            _data_filler = ','.join([f'{x}=?' for x in kwargs if x != 'id'])
            self.cur.execute(f'update {_table_name} set {_data_filler} where id = {_data[0]!r}', _data[1:])
        elif self.db_type == 'mysql':
            _data = [f'{a}={b!r}' for a, b in zip(kwargs.keys(), kwargs.values())]
            self.cur.execute(f'update {_table_name} set {",".join(_data[1:])} where {_data[0]}')
        self.db.commit()

    @with_cursor
    def fetch_data(self, query: str):
        self.cur.execute(query)
        data = self.cur.fetchall()
        cols = [x[0] for x in self.cur.description]
        return pd.DataFrame(data, columns=cols)

    @with_cursor
    def execute(self, query: str):
        self.cur.execute(query)
        self.db.commit()

    @with_cursor
    def add_channels_data(self, _df: pd.DataFrame):
        _df = _df[['id', 'thumbnails', 'title', 'description', 'viewCount', 'subscriberCount', 'videoCount']]

        for i, r in _df.iterrows():
            try:
                self.insert_data('channels', **r)
            except Exception as e:
                if str(e).startswith(('1062 (23000): Duplicate entry', 'UNIQUE constraint failed:')):
                    self.update_data('channels', **r)
                else:
                    raise e

    @with_cursor
    def add_playlists_data(self, _df: pd.DataFrame):
        _df = _df[['id', 'channelId', 'thumbnails', 'title', 'description', 'publishedAt', 'itemCount']]
        _df.publishedAt = _df.publishedAt.apply(lambda x: x.split('Z')[0].replace('T', ' '))

        for i, r in _df.iterrows():
            try:
                self.insert_data('playlists', **r)
            except Exception as e:
                if str(e).startswith(('1062 (23000): Duplicate entry', 'UNIQUE constraint failed:')):
                    self.update_data('playlists', **r)
                elif str(e).startswith(('1452 (23000): Cannot add or update a child row',
                                        'FOREIGN KEY constraint failed')):
                    st.toast(f':red[{e}]')
                else:
                    raise e

    @with_cursor
    def add_videos_data(self, _df: pd.DataFrame):
        _df = _df[['id', 'channelId', 'playlistId', 'thumbnails', 'title', 'description', 'publishedAt',
                   'duration', 'viewCount', 'likeCount', 'dislikeCount', 'commentCount']]
        _df.duration = _df.duration.apply(lambda x: str(x)[-8:])

        for i, r in _df.iterrows():
            try:
                self.insert_data('videos', **r)
            except Exception as e:
                if str(e).startswith(('1062 (23000): Duplicate entry', 'UNIQUE constraint failed:')):
                    self.update_data('videos', **r)
                elif str(e).startswith(('1452 (23000): Cannot add or update a child row',
                                        'FOREIGN KEY constraint failed')):
                    st.toast(f':red[{e}]')
                else:
                    raise e

    @with_cursor
    def add_comments_data(self, _df: pd.DataFrame):
        _df = _df[['id', 'channelId', 'videoId', 'authorProfileImage', 'textDisplay',
                   'textOriginal', 'likeCount', 'publishedAt', 'updatedAt']]
        _df.publishedAt = _df.publishedAt.apply(lambda x: x.split('Z')[0].replace('T', ' '))
        _df.updatedAt = _df.updatedAt.apply(lambda x: x.split('Z')[0].replace('T', ' '))

        for i, r in _df.iterrows():
            try:
                self.insert_data('comments', **r)
            except Exception as e:
                if str(e).startswith(('1062 (23000): Duplicate entry', 'UNIQUE constraint failed:')):
                    self.update_data('comments', **r)
                elif str(e).startswith(('1452 (23000): Cannot add or update a child row',
                                        'FOREIGN KEY constraint failed')):
                    st.toast(f':red[{e}]')
                else:
                    raise e


class YTAPI(object):

    def __init__(self, _api_keys: list[str]):
        self.yt_apis = [build('youtube',
                              'v3', developerKey=_api) for _api in _api_keys]

    def search_list(self, text: str,
                    typ: Literal['channel', 'playlist', 'video'] = 'channel'):
        for _yt in self.yt_apis:
            try:
                _res = self.yt_apis[0].search().list(
                    part='snippet',
                    type=typ,
                    maxResults=50,
                    q=text).execute()
                return _res
            except Exception as e:
                print(f'function search_list: {e}')

    def channel_list(self, _channel_id: str):
        for _yt in self.yt_apis:
            try:
                _res = _yt.channels().list(
                    part='snippet,contentDetails,statistics',
                    # fields='nextPageToken,prevPageToken,items(snippet(channelId,thumbnails(default),channelTitle))',
                    id=_channel_id).execute()
                return _res
            except Exception as e:
                # self.yt_apis.remove(_yt)
                print(f'function channel_list: {e}')

    def playlists_list(self, **kwargs):
        for _yt in self.yt_apis:
            try:
                _res = _yt.playlists().list(
                    part='snippet,contentDetails',
                    maxResults=50,
                    **kwargs).execute()
                return _res
            except Exception as e:
                print(f'function playlists_list: {e}')

    def playlist_items_list(self, _playlist_id: str, _page_token: str | None = None):
        for _yt in self.yt_apis:
            try:
                _res = _yt.playlistItems().list(
                    part='snippet,status',
                    # fields='nextPageToken,items(snippet(resourceId(videoId)))',
                    pageToken=_page_token,
                    maxResults=50,
                    playlistId=_playlist_id).execute()
                return _res
            except Exception as e:
                print(f'function playlist_items_list: {e}')

    def videos_list(self, _video_id: str):
        for _yt in self.yt_apis:
            try:
                _res = _yt.videos().list(
                    part='snippet,contentDetails,statistics',
                    id=_video_id).execute()
                return _res
            except Exception as e:
                print(f'function videos_list: {e}')

    def comment_threads_list(self, _channel_id: str, **kwargs):
        for _yt in self.yt_apis:
            try:
                _res = _yt.commentThreads().list(
                    part='id,replies,snippet',
                    allThreadsRelatedToChannelId=_channel_id,
                    maxResults=100,
                    **kwargs).execute()
                return _res
            except Exception as e:
                print(f'function comment_threads_list: {e}')

    def get_channels_df(self, _channel_id):
        es = '''{'id': x.id, 'thumbnails': x.snippet['thumbnails']['default']['url'],
        'title': x.snippet['title'], 'description': x.snippet['description'],
        'viewCount': int(x.statistics['viewCount']), 'subscriberCount': int(x.statistics['subscriberCount']),
        'videoCount': int(x.statistics['videoCount']), 'uploads': x.contentDetails['relatedPlaylists']['uploads']}'''

        res = self.channel_list(_channel_id)
        _df = pd.DataFrame(res['items'])
        df = _df.apply(lambda x: eval(es), axis=1, result_type='expand')
        return df

    def get_playlists_df(self, **kwargs):
        es = '''{'id': x.id, 'channelId': x.snippet['channelId'],
        'thumbnails': x.snippet['thumbnails']['default']['url'], 'title': x.snippet['title'],
        'description': x.snippet['description'], 'publishedAt': x.snippet['publishedAt'],
        'itemCount': int(x.contentDetails['itemCount'])}'''

        res = self.playlists_list(**kwargs)
        _df = pd.DataFrame(res['items'])
        df = _df.apply(lambda x: eval(es), axis=1, result_type='expand')

        while res.get('nextPageToken'):
            res = self.playlists_list(pageToken=res.get('nextPageToken'), **kwargs)
            _df = pd.DataFrame(res['items'])
            df = pd.concat([df, _df.apply(lambda x: eval(es), axis=1, result_type='expand')])

        return df

    def get_videos_df(self, _playlist_id: str):
        es = '''{'id': x.id, 'channelId': x.snippet["channelId"], 'playlistId': '',
        'thumbnails': x.snippet['thumbnails']['default']['url'], 'title': x.snippet['title'],
        'description': x.snippet['description'], 'publishedAt': x.snippet['publishedAt'],
        'duration': x.contentDetails['duration'], 'viewCount': int(x.statistics.get('viewCount', 0)),
        'likeCount': int(x.statistics.get('likeCount', 0)), 'dislikeCount': int(x.statistics.get('dislikeCount', 0)),
        'commentCount': int(x.statistics.get('commentCount', 0))}'''
        data = []

        res = self.playlist_items_list(_playlist_id)
        vid = [x['snippet']['resourceId']['videoId'] for x in res['items']]
        data.extend(self.videos_list(','.join(vid))['items'])

        while res.get('nextPageToken'):
            res = self.playlist_items_list(_playlist_id, res.get('nextPageToken'))
            vid = [x['snippet']['resourceId']['videoId'] for x in res['items']]
            data.extend(self.videos_list(','.join(vid))['items'])

        df = pd.DataFrame(data).apply(lambda x: eval(es), axis=1, result_type='expand')
        if not df.empty:
            df.playlistId = _playlist_id
            df.publishedAt = df.publishedAt.apply(lambda x: x.split('Z')[0].replace('T', ' '))
            df.duration = pd.to_timedelta(df.duration.str[1:].str.replace('T', '').str.lower())

        return df

    def get_comments_df(self, _channel_id):
        es = '''{'id': x.id, 'channelId': x.snippet["channelId"], 'videoId': x.snippet['videoId'],
                'authorProfileImage': x.snippet['topLevelComment']['snippet']['authorProfileImageUrl'],
                'textDisplay': x.snippet['topLevelComment']['snippet']['textDisplay'],
                'textOriginal': x.snippet['topLevelComment']['snippet']['textOriginal'],
                'likeCount': x.snippet['topLevelComment']['snippet']['likeCount'],
                'publishedAt': x.snippet['topLevelComment']['snippet']['publishedAt'],
                'updatedAt': x.snippet['topLevelComment']['snippet']['updatedAt']}'''

        res = self.comment_threads_list(_channel_id)
        _df = pd.DataFrame(res['items'])
        df = _df.apply(lambda x: eval(es), axis=1, result_type='expand')

        return df


def set_creds() -> [YTAPI, YTDataBase]:
    st.session_state['yt_api_creds'] = st.session_state.get('yt_api_creds') or st.secrets.YouTubeAPI['apis']
    _api = st.session_state.get('yt_api') or YTAPI(st.session_state.yt_api_creds)
    st.session_state['yt_api'] = _api

    st.session_state['yt_db_creds'] = st.session_state.get('yt_db_creds') or dict(st.secrets.YouTubeDataBase)
    _db = st.session_state.get('yt_db') or YTDataBase(**st.session_state.yt_db_creds)
    st.session_state['yt_db'] = _db

    return _api, _db


if __name__ == '__main__':
    yt_api, yt_db = set_creds()
    '# Hi, Welcome to my Page 🎉'
    ''
    with open('README.md', 'r') as f:
        for li in f.readlines():
            st.markdown(li)
