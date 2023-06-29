from flask import Flask, render_template, request, jsonify
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from settings import YOUTUBE_API_KEY, SECRET_KEY
import requests
import logging
import re
from urllib.parse import urlparse, parse_qs
from contextlib import suppress

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY

logging.basicConfig(filename='app.log', level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')


class VideoForm(FlaskForm):
    video_id = StringField('Video ID', validators=[DataRequired()])
    submit = SubmitField('Get Info')


@app.route('/', methods=['GET', 'POST'])
def index():
    form = VideoForm()
    return render_template('index.html', form=form)


@app.route('/get_video_info', methods=['POST'])
def get_video_info():
    video_url = request.form.get('video_id')
    video_id = get_youtube_video_id(video_url)

    if video_id:
        # Try to get video transcript
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
            transcript = " ".join([x['text'] for x in transcript_list])
        except NoTranscriptFound:
            transcript = "Nessuna trascrizione disponibile per il video specificato."

        # Eseguiamo la richiesta API per ottenere le informazioni del video
        api_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={video_id}&key={YOUTUBE_API_KEY}"
        response = requests.get(api_url)
        data = response.json()

        # Otteniamo i tag del video
        try:
            tags = data['items'][0]['snippet']['tags']
        except KeyError:
            tags = "Impossibile trovare i tag per il video specificato."

        video_info = {'transcript': transcript, 'tags': tags}
        return jsonify(video_info)
    else:
        return jsonify({'error': 'URL del video non valido'})


def get_youtube_video_id(url):
    query = urlparse(url)
    video_id = None

    if query.hostname == 'youtu.be':
        video_id = query.path[1:]
    elif query.hostname in {'www.youtube.com', 'youtube.com', 'music.youtube.com'}:
        with suppress(KeyError):
            video_id = parse_qs(query.query)['list'][0]
        if query.path == '/watch':
            video_id = parse_qs(query.query)['v'][0]
        if query.path[:7] == '/watch/':
            video_id = query.path.split('/')[1]
        if query.path[:7] == '/embed/':
            video_id = query.path.split('/')[2]
        if query.path[:3] == '/v/':
            video_id = query.path.split('/')[2]

    if video_id:
        logging.debug(f"ID del video: {video_id}")
    else:
        logging.debug("Nessun ID video estratto")

    return video_id


if __name__ == "__main__":
    app.run(debug=True)
