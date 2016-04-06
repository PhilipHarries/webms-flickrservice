import datetime, flickr_api, pytz, os
import cStringIO,mimetypes,requests
from flask import Flask, jsonify, abort, make_response, request, url_for, send_file
from flask.ext.pymongo import PyMongo
from pymongo import MongoClient
from datetime import timedelta
from PIL import Image
from bson import Binary
import logging
from logging.handlers import RotatingFileHandler
from dateutil.parser import parse as parse_date

cacheTimeoutDays = 1

app = Flask(__name__)
handler = RotatingFileHandler('./logs/flickrservice.log',maxBytes=40960,backupCount=3)
handler.setLevel(logging.DEBUG)
app.logger.addHandler(handler)
log = logging.getLogger('werkzeug')
log.setLevel(logging.DEBUG)
log.addHandler(handler)




debug = False

def epr(s):
    app.logger.error(s)
    if(debug):
        print s

def dpr(s):
    app.logger.debug(s)
    if(debug):
        print s


try:
    api_key = os.environ['FLICKR_API_KEY']
    api_secret = os.environ['FLICKR_API_SECRET']
except KeyError as KE:
    epr("Bailing out: environment variable missing: {}".format(KE))
    exit(1)
    
# connect to mongo with defaults
mongo = PyMongo(app)


# a user is just an id
# an album should have  a title, an id, a description, a last-update and a list of pictures (picture ids?)
def get_user_albums_from_flickr(the_user):
    flickr_api.set_keys(api_key = api_key, api_secret = api_secret)
    user = flickr_api.Person.findByUserName(the_user)
    album_list = []
    dpr("Getting User Albums for {}".format(the_user))
    try:
        for photoset in user.getPhotosets():
            photosetinfo=photoset.getInfo()
            photoInfo=[]
            album_list.append({
                "title": photosetinfo["title"],
                "id":    photosetinfo["id"],
                "desc":  photosetinfo["description"],
                "album-last-update": photosetinfo["date_update"],
                "cache-last-update": datetime.datetime.utcnow(),
                "owner_id": the_user,
                "photos": photoInfo,
            })
    except Exception as e:
        dpr(e)
        abort(503)
    return album_list

def get_album_from_flickr(the_user,the_album_id):
    flickr_api.set_keys(api_key = api_key, api_secret = api_secret)
    dpr("Getting user {}".format(the_user))
    try:
        user = flickr_api.Person.findByUserName(the_user)
    except Exception as e:
        abort(500)
    photoset=""
    try:
        dpr("Getting albums for user...")
        for thisPhotoset in user.getPhotosets():
            if thisPhotoset.getInfo()["id"] == the_album_id:
                photoset=thisPhotoset
                dpr("Found album {}".format(the_album_id))
                break
        if photoset == "":
            return None
        else:
            photosetinfo=photoset.getInfo()
            usercode=photosetinfo["owner"]["id"]
            photoInfo=[]
            photos=photoset.getPhotos()
            for photo in photos:
                dpr(photo)
                photoInfo.append({"id": photo["id"], "title": photo["title"], "usercode": usercode })
            return {
                "title": photosetinfo["title"],
                "id":    photosetinfo["id"],
                "desc":  photosetinfo["description"],
                "album-last-update": photosetinfo["date_update"],
                "cache-last-update": datetime.datetime.utcnow(),
                "owner_id": the_user,
                "photos": photoInfo,
           }
    except Exception as e:
        dpr(e)
        #abort(500)

def get_album_from_db(user_id,album_id):
    cursor=mongo.db.albums.find({"owner_id": { "$exists": "true" } })
    matched_albums = [album for album in cursor if (album["owner_id"] == user_id and album["id"] == album_id)]
    dpr("matched_albums: {}".format(matched_albums))
    if len(matched_albums) != 0:
        for album in matched_albums:
            dpr("album in matched_albums id: {}".format(album["id"]))
        album=matched_albums[0]
    else:
        album=""
    dpr("{}".format(album))
    return album

def get_album(user_id,album_id,force=False):
    album=""
    get_from_flickr = False
    if force:
        get_from_flickr = True
    else:
        album=get_album_from_db(user_id,album_id)
        if (album == ""):
            dpr("We do not have a cached version of the album!")
            get_from_flickr = True
        if "cache-last-update" in album:
            dpr("parsing cache-last-update: {}".format(album["cache-last-update"]))
            datestamp = album["cache-last-update"]
            if type(datestamp) is not datetime.datetime:
                datestamp = parse_date(album["cache-last-update"])
        else:
            dpr("No cache-last-update recorded in album - so setting it to 10 years ago")
            datestamp = (datetime.datetime.utcnow() - timedelta(days=3650)).replace(tzinfo=pytz.UTC)
        # if the cache hasn't been updated for a period of time, or if there no photos yet loaded, we'll refresh 
        # should do more tests here
        if datestamp < (datetime.datetime.utcnow() - timedelta(days=cacheTimeoutDays)).replace(tzinfo=pytz.UTC) or len(album["photos"]) == 0:
            dpr("datestamp of cached version is older than {} days".format(cacheTimeoutDays))
            get_from_flickr = True

    if get_from_flickr:
        album=get_album_from_flickr(user_id,album_id)
        if not album:
            epr("Could not find album {} in flickr!".format(album_id))
            abort(404)
        mongo.db.albums.update_one(
            {"owner_id": user_id, "id": album["id"]},
            { "$set":
                {
                    "owner_id": album["owner_id"],
                    "id": album["id"],
                    "title": album["title"],
                    "cache-last-update": datetime.datetime.utcnow(),
                    "album-last-update": album["album-last-update"],
                    "desc": album["desc"],
                    "photos": album["photos"],
                }
            }, upsert = True
        )
    return album


def get_image_from_flickr(the_user,the_album_id,the_photo_id,the_data_type):
    # get hold of the image info from flickr
    #  - specifically the height, width and url for the picture type (Medium, Thumbnail, Link, etc.)
    #  - and obviously the datastream for the image
    dpr(the_user)
    dpr(the_album_id)
    dpr(the_photo_id)
    flickr_api.set_keys(api_key = api_key, api_secret = api_secret)
    dpr("Getting user from flickr")
    user = flickr_api.Person.findByUserName(the_user)
    photo=""
    #photoset=""
    dpr("Getting user photos from flickr")
    gpp = flickr_api.Walker(user.getPublicPhotos)
    for thisPhoto in gpp:
        if thisPhoto["id"] == the_photo_id:
            photo = thisPhoto
            dpr("got photo from flickr")
            break

    if photo == "":
        dpr("My photo gave you None")
        return None
        
    dpr("You have a photo, with sizes.  You want {}.".format(the_data_type))
    photo_sizes=photo.getSizes()
    if the_data_type in photo_sizes:
        dpr("I have a picture that is {}!".format(the_data_type))
        pass
    else:
        dpr("Look, I don't have a {}, but I have these things:".format(the_data_type))
        for p in photo_sizes:
            dpr(p)
    for p in photo_sizes:
        if p == the_data_type:
            url = photo_sizes[p]["source"]
            r = requests.get(url, stream=True)
            r.raw.decode_content=True
            data=Binary(r.raw.read())
            return {
                    "id": the_photo_id,
                    "url {}".format(the_data_type): url,
                    "height {}".format(the_data_type): photo_sizes[p]["height"],
                    "width {}".format(the_data_type): photo_sizes[p]["width"],
                    "data {}".format(the_data_type): data
                }

def make_public_album(album, with_pictures=False):
    prettified_album = {}
    for field in album:
        if field == 'id':
            prettified_album['uri'] = url_for(
                                    'get_this_album',
                                    album_id=album['id'],
                                    user_id=album['owner_id'],
                                    _external = True
                                    )
        if field == 'photos':
            if with_pictures:
                prettified_album['photos'] = []
                for photo in album['photos']:
                    prettified_album['photos'].append({
                        'photo': url_for( 'get_image',
                            image_type = "photo",
                            user_id = album['owner_id'],
                            album_id = album['id'],
                            photo_id = photo['id'],
                            _external = True
                        ),
                        'thumbnail': url_for( 'get_image',
                            image_type = "thumbnail",
                            user_id = album['owner_id'],
                            album_id = album['id'],
                            photo_id = photo['id'],
                            _external = True
                        ),
                        'id': photo['id'],
                        'flickr_url': "https://www.flickr.com/photos/{}/{}".format(photo['usercode'],photo['id']),
                        'title': photo['title']
                    })
            else:
                pass
            prettified_album['num_photos'] = len(album['photos'])
        elif field == '_id':
            pass
        else:
            try:
                prettified_album[field] = album[field]
            except Exception as e:
                dpr("{} - {}".format(field, e))
    return prettified_album


def make_public_user(user):
    new_user = {}
    for field in user:
        if field == 'id':
            new_user['uri'] = url_for(
                                    'get_user',
                                    user_id=user['id'],
                                    _external = True
                                    )
        if field == '_id':
            pass
        else:
            try:
                new_user[field] = user[field]
            except Exception as e:
                dpr("{} - {}".format(field, e))
    return new_user

@app.errorhandler(404)
def not_found(error):
    dpr(error)
    return make_response(jsonify({'error': '404: not found'}), 404)

@app.errorhandler(400)
def bad_request(error):
    dpr(error)
    return make_response(jsonify({'error': '400: bad request'}), 400)

@app.errorhandler(409)
def bad_request(error):
    dpr(error)
    return make_response(jsonify({'error': '409: duplicate resource id'}), 409)

@app.errorhandler(500)
def internal_server_error(error):
    dpr(error)
    return make_response(jsonify({'error': '500: internal server error'}), 500)

@app.errorhandler(501)
def not_implemented(error):
    dpr(error)
    return make_response(jsonify({'error': '501: HTTP request not understood in this context'}), 501)

@app.errorhandler(502)
def bad_gateway(error):
    dpr(error)
    return make_response(jsonify({'error': '502: server received an invalid response from an upstream server'}), 502)

@app.errorhandler(503)
def service_unavailable(error):
    dpr(error)
    return make_response(jsonify({'error': '503: service unavailable - try back later'}), 503)

@app.errorhandler(504)
def gateway_timeout(error):
    dpr(error)
    return make_response(jsonify({'error': '504: upstream timeout - the server stopped waiting for a response from upstream'}), 504)

@app.route('/flickr/api/v1.0/users', methods=['GET'])
def get_users():
    users=[]
    cursor=mongo.db.users.find()
    for user in cursor:
        users.append(user)
    if len(users) !=0:
        return jsonify({'users': [make_public_user(user) for user in users]})
    else:
        abort(404)

@app.route('/flickr/api/v1.0/user/<string:user_id>', methods=['GET'])
def get_user(user_id):
    cursor=mongo.db.users.find()
    user = [user for user in cursor if user['id'] == user_id]
    if len(user) == 0:
        abort(404)
    return jsonify({'user': make_public_user(user[0])})

@app.route('/flickr/api/v1.0/user/<string:user_id>', methods=['DELETE'])
def delete_user(user_id):
    user=mongo.db.users.find_one_or_404({'id': user_id})
    if len(user) == 0:
        abort(404)
    mongo.db.users.remove({"id": user_id})
    mongo.db.pictures.remove({"owner_id": user_id})
    return jsonify({'result': True})


@app.route('/flickr/api/v1.0/users', methods=['POST'])
def create_user():
    if not request.json or not 'id' in request.json:
        abort(400)
    user = {
        'id': request.json['id'],
        }
    cursor=mongo.db.users.find({'id': user['id']}).limit(1)
    if cursor.count() > 0:
        abort(409)

    mongo.db.users.insert(user)
    return jsonify({'user': make_public_user(user)}), 201

@app.route('/flickr/api/v1.0/refresh_albums', methods=['POST'])
def refresh_albums():
    content = request.get_json(silent=True)
    dpr(content)
    album_ids = content["album_ids"]
    owner_id = content["owner_id"]
    dpr(album_ids)
    count=0
    for album_id in album_ids:
        dpr(album_id)
        cursor = mongo.db.albums.find({"owner_id": owner_id, "album_id": album_id})
        album=get_album(owner_id,album_id,force=True)
        if album:
            count=count + 1
    return jsonify({"updated": count})

@app.route('/flickr/api/v1.0/albums/<string:user_id>', methods=['GET'])
def get_albums(user_id):
    albums=[]
    dpr("Operating on user: {} ".format(user_id))
    cursor=mongo.db.albums.find({"owner_id": user_id})
    cursor.sort([("id",1)])
    cursor.rewind()
    dpr("Getting albums from cache")
    now=datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
    dpr("It is {}".format(now))
    cacheInfo = ""
    try:
        dpr("Connecting to mongo")
        albums = [album for album in cursor if album["owner_id"] == user_id]
        dpr("Got albums, rewinding cursor")
        cursor.rewind()
        dpr("Getting cache information")
        cacheInfo = [cache for cache in cursor if cache["id"] == "cacheInfo" ]
        dpr("Cache Info is {}".format(cacheInfo))
    except KeyError as K:
        dpr("Received KeyError: {} but ignoring".format(K))
        pass
    if len(cacheInfo) != 0:
        cacheInfo = cacheInfo[0]
    else:
        cacheInfo = { "cache-last-update": (datetime.datetime.utcnow() - timedelta(days=3650)).replace(tzinfo=pytz.UTC) }

    if len(albums) != 0:
        dpr("we have some albums cached")
        cacheDateStamp = cacheInfo["cache-last-update"]
        if cacheDateStamp < (datetime.datetime.utcnow() - timedelta(days=cacheTimeoutDays)).replace(tzinfo=pytz.UTC):

            dpr("cache is older than 1 day")
            dpr("cacheDateStamp: {}  now: {}".format(cacheDateStamp,datetime.datetime.utcnow()))
            dpr("{} day(s) ago: {}".format(cacheTimeoutDays,(datetime.datetime.utcnow() - timedelta(days=cacheTimeoutDays))))

            albums=get_user_albums_from_flickr(user_id)
            for album in albums:
                try:
                    mongo.db.albums.insert(
                        { "id": album["id"] },
                        { "$set": 
                            {
                                "owner_id": album["owner_id"],
                                "id": album["id"],
                                "title": album["title"],
                                "album-last-update": album["album-last-update"],
                                "desc": album["desc"],
                                "photos": album["photos"],
                            }
                        }, True  # upsert
                    )
                except KeyError as K:
                    pass
            dpr("Updating cache info")
            mongo.db.albums.update({"id": "cacheInfo"}, { "$set": { "cache-last-update": now , "owner_id": user_id }, }, True)
        else:
            dpr("cache is younger than 1 day old")
    else:
        # better load albums into cache
        dpr("We do not have any albums in the cache - at all")
        dpr("We're going to load some albums into cache")
        albums=get_user_albums_from_flickr(user_id)
        for album in albums:
            mongo.db.albums.update(
                { "id": album["id"] },
                { "$set": 
                    {
                        "owner_id": album["owner_id"],
                        "id": album["id"],
                        "title": album["title"],
                        "album-last-update": album["album-last-update"],
                        "desc": album["desc"],
                        "photos": album["photos"],
                    }
                }, True
            )
        dpr("Updating cache info")
        mongo.db.albums.update({"id": "cacheInfo"}, { "$set": { "cache-last-update": now, "owner_id": user_id }, }, True)

    if len(albums) !=0:
        return jsonify({'albums': [make_public_album(album) for album in albums]})
    else:
        # we don't have any albums, and we couldn't find any albums, so 404
        abort(404)







@app.route('/flickr/api/v1.0/album/<string:user_id>/<string:album_id>', methods=['GET'])
def get_this_album(user_id,album_id):
    return jsonify({'album': make_public_album(get_album(user_id,album_id), True)})


@app.route('/flickr/api/v1.0/album/<string:user_id>/<string:album_id>/<int:chunk_size>/<int:chunk_number>', methods=['GET'])
def get_album_chunk(user_id,album_id,chunk_size,chunk_number):
    album=get_album(user_id,album_id)
    num_photos=len(album["photos"])
    num_chunks=1
    dpr("number of photos: {}".format(num_photos))
    if ((num_photos % chunk_size) == 0):
        num_chunks=num_photos // chunk_size
    else:
        num_chunks=(num_photos // chunk_size) + 1
    dpr("num_chunks: {} for chunk_size: {}".format(num_chunks,chunk_size))
    if chunk_size < 1:
        epr("invalid chunk size")
        abort(400)
    if chunk_number >= num_chunks:
        epr("invalid chunk number")
        abort(400)
    start_at = chunk_size * chunk_number
    chunk = []
    for index in range(start_at,min(start_at + chunk_size,num_photos)):
        chunk.append(album["photos"][index])
    album["photos"] = chunk
    album["num_chunks"] = num_chunks
    album["chunk_num"] = chunk_number
    album["chunk_size"] = chunk_size
    album["num_photos_in_album"] = num_photos
    return jsonify({'album': make_public_album(album, True)})
    




# get this right now, but actually would like images to be able to store
# thumbnails and 'main' pictures
# (updating each only when required)
@app.route('/flickr/api/v1.0/<string:image_type>/<string:user_id>/<string:album_id>/<string:photo_id>', methods=['GET'])
def get_image(image_type,user_id,album_id,photo_id):
    if image_type=="thumbnail":
        image_type="Thumbnail"
    elif image_type=="photo":
        image_type="Medium"
    cursor=mongo.db.images.find({"id": photo_id})
    images = [image for image in cursor]
    this_image=""
    if len(images) == 0:
        #print "This image is not present in the cache"
        # we don't know about this image so get image from flickr
        this_image=get_image_from_flickr(user_id,album_id,photo_id,image_type)
        # store that mofo in the db
        mongo.db.images.insert(this_image,True)
    else:
        #print "This image is present (in some form) in the cache"
        this_image=images[0]
        if "data {}".format(image_type) not in this_image:
            # we know about image, but have never retrieved this format
            dpr("Know about the image, but don't have {} cached".format(image_type))
            try:
                new_data_for_image=get_image_from_flickr(user_id,album_id,photo_id,image_type)
            except Exception as e:
                dpr("Could not fetch photo from flickr! {}".format(e))
                abort(404)
            if new_data_for_image == "":
                # couldn't find what you're looking for
                abort(404)
            dpr("Got new image information for type: {}".format(image_type))

            result=mongo.db.images.update( {"id": photo_id},
                {
                    "$set": {
                        "data {}".format(image_type): new_data_for_image["data {}".format(image_type)]
                    },
                }, True)
            dpr("Had a go at updating the mongo db image and got the result: {}".format(result))
            cursor=mongo.db.images.find({"id": photo_id})
            this_image = [image for image in cursor][0]
    if this_image == "":
        abort(404)
    img_io = cStringIO.StringIO() 
    img_io.write(this_image["data {}".format(image_type)])
    img_io.seek(0)
    return send_file(img_io, mimetype='image/jpeg')

if __name__ == '__main__':
    app.run(debug=True, threaded=True, port=6542, host='0.0.0.0')

