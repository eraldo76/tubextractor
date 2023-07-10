from flask import Flask, render_template, request, jsonify, send_file, session, Response, send_from_directory
from flask_session import Session
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
import youtube_dl
import json
import os
import isodate
from flask_minify import minify

# FLASK_APP=app.py FLASK_DEBUG=true flask run
app = Flask(__name__)

# Initialize Flask-Minify
minify(app=app)

# Configure the session
SESSION_TYPE = 'filesystem'
app.config.from_object(__name__)
Session(app)

app.config['SECRET_KEY'] = SECRET_KEY

logging.basicConfig(filename='app.log', level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')


class VideoForm(FlaskForm):
    video_id = StringField('Video ID', validators=[DataRequired()])
    submit = SubmitField('Get Info')


@app.route('/', methods=['GET', 'POST'])
def index():
    form = VideoForm()
    video_info = {}  # Initialize the variable video_info as an empty dictionary
    if form.validate_on_submit():
        video_url = form.video_id.data
        payload = {'video_id': video_url}
        headers = {'Content-Type': 'application/json'}
        base_url = request.base_url  # Get the current base URL
        response = requests.post(
            f"{base_url}get_video_info", data=json.dumps(payload), headers=headers)
        video_info = response.json()
    return render_template('index.html', form=form, video_info=video_info)


@app.route('/get_video_info', methods=['POST'])
def fetch_video_info():
    video_id_or_url = request.json.get('video_id')
    video_id = None  # Initialize video_id here
    logging.debug(f"Fetching video info for ID or URL: {video_id_or_url}")

    # Check if video_id_or_url is not None and, if so, proceed
    if video_id_or_url is not None:
        # Check if video_id_or_url is a URL and, if so, extract the video ID
        if 'http' in video_id_or_url:
            video_id = get_youtube_video_id(video_id_or_url)
        else:
            video_id = video_id_or_url

    logging.debug(f"Video ID: {video_id}")

    # Save the video_id in the session
    session['video_id'] = video_id

    if video_id is None:
        return jsonify({'error': 'URL del video non valido'})

    # rest of your code follows
    ...

    if video_id:
       # Try to get video transcript
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(
                video_id, languages=['it', 'en', 'es', 'de'])
            transcript = " ".join([x['text'] for x in transcript_list])
        except Exception as e:
            transcript = str(e)
            app.logger.error(f"Error getting transcript: {str(e)}")
        # We run the API request to get the video information
        video_id = video_id.split('?')[0] if '?' in video_id else video_id
        api_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails&id={video_id}&key={YOUTUBE_API_KEY}"
        response = requests.get(api_url)
        data = response.json()

        # print data json
        logging.info(json.dumps(data, indent=4))

        # Check if data['items'] is empty
        if not data['items']:
            return jsonify({'error': 'No video information returned from YouTube API'})

        # We get the title
        title = data['items'][0]['snippet']['title']

        # Get the video's thumbnail URL
        thumbnail_url = data['items'][0]['snippet']['thumbnails']['medium']['url']

        # We get the name of the channel or author who posted the video
        channel_title = data['items'][0]['snippet']['channelTitle']

        duration = data['items'][0]['contentDetails']['duration']
        duration_timedelta = isodate.parse_duration(duration)

        # We get the video tags
        try:
            tags = data['items'][0]['snippet']['tags']
        except KeyError:
            tags = []

        # Get the available video formats
        ydl_opts = {
            'ignoreerrors': True,
        }
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(video_id, download=False)
            formats = info_dict.get('formats') if info_dict else []

            format_info = []
            for format in formats:
                if format["acodec"] != "none":  # We want video formats with audio
                    format_info.append({
                        'format_id': format["format_id"],
                        'format_note': format["format_note"],
                        'ext': format["ext"],
                        'url': format['url']  # Add the direct download URL
                    })

        video_info = {
            'transcript': transcript,
            'tags': tags,
            'title': title,
            'channel_title': channel_title,
            'thumbnail': thumbnail_url,
            'duration': str(duration_timedelta),
            'formats': format_info,
        }
        return jsonify(video_info) if video_info else jsonify({'error': 'Impossibile ottenere le informazioni del video'})
    else:
        return jsonify({'error': 'URL del video non valido'})


def get_youtube_video_id(url):
    logging.debug(f"get_youtube_video_id called with url: {url}")
    query = urlparse(url)
    video_id = None

    logging.debug(f"query.hostname: {query.hostname}")
    logging.debug(f"query.path: {query.path}")

    if query.hostname == 'youtu.be':
        video_id = query.path[1:]
    elif query.hostname in {'www.youtube.com', 'youtube.com', 'music.youtube.com'}:
        if query.path == '/watch':
            video_id = parse_qs(query.query)['v'][0]
        elif query.path[:3] == '/v/':
            video_id = query.path.split('/')[2]
        elif query.path[:7] == '/embed/':
            video_id = query.path.split('/')[2]
        elif query.path[:7] == '/shorts/':  # Add this condition
            # Add this line to remove "?feature=share"
            video_id = query.path.split('/')[2].split('?')[0]

    if video_id:
        logging.debug(f"Video ID: {video_id}")
    else:
        logging.debug("No video ID extracted")

    return video_id


@app.route('/download_video/<format_id>', methods=['GET'])
def download_video(format_id):
    # We use the video_id from the session here
    video_id = session.get('video_id', None)

    # If we don't have a video_id, we can't continue
    if not video_id:
        return jsonify({'error': 'Nessun video selezionato'}), 400

    # Define youtube-dl options
    ydl_opts = {
        'format': format_id,  # Use the format chosen by the user
        'outtmpl': 'temp/%(id)s.%(ext)s'  # Save the file in the /temp folder
    }

    # Download the video
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        try:
            info_dict = ydl.extract_info(video_id, download=True)
            filename = ydl.prepare_filename(info_dict)
        except Exception as e:
            app.logger.error(f"Error downloading video: {str(e)}")
            return jsonify({'error': 'Errore nel download del video'}), 500

    # If the file was downloaded successfully, send it to the user
    try:
        return send_file(filename, as_attachment=True)
    finally:
        # After sending the file to the user, remove it from the server
        if os.path.exists(filename):
            os.remove(filename)

# Download Audio


@app.route('/download_audio', methods=['GET'])
def download_audio():
    # We use the video_id from the session here
    video_id = session.get('video_id', None)

    # If we don't have a video_id, we can't continue
    if not video_id:
        return jsonify({'error': 'Nessun video selezionato'}), 400

    # Define youtube-dl options
    ydl_opts = {
        'format': 'bestaudio/best',  # Use the best audio format
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': 'temp/%(id)s.%(ext)s'  # Save the file in the /temp folder
    }

    # Download the audio
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        try:
            info_dict = ydl.extract_info(video_id, download=True)
            filename = ydl.prepare_filename(info_dict)
            converted_filename = filename.rsplit(".", 1)[0] + ".mp3"

            # If the file was downloaded successfully, send it to the user
            return send_file(converted_filename, mimetype='audio/mpeg', as_attachment=True)
        except Exception as e:
            app.logger.error(f"Error downloading audio: {str(e)}")
            return jsonify({'error': 'Errore nel download dell\'audio'}), 500
        finally:
            # After sending the file to the user, remove it from the server
            if os.path.exists(converted_filename):
                os.remove(converted_filename)


@app.route('/robots.txt')
@app.route('/sitemap.xml')
def static_from_root():
    return send_from_directory(app.static_folder, request.path[1:])


# sitemap


# @app.route('/sitemap.xml')
# def sitemap():
#     sitemap_xml = render_template('sitemap.xml')
#     response = Response(sitemap_xml, mimetype='application/xml')
#     return response

# privacy-policy


@app.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy-policy.html')

# terms-of-service


@app.route('/terms-of-service')
def privacy():
    return render_template('terms-of-service.html')
# adsense


@app.route('/ads.txt')
def ads_txt():
    return app.send_static_file('ads.txt')


# main
if __name__ == "__main__":
    app.run(debug=True)
