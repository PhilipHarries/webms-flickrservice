this is the flickrservice.

port = '5433',
@app.route('/flickr/api/v1.0/users', methods=['GET'])
@app.route('/flickr/api/v1.0/user/<string:user_id>', methods=['GET'])
@app.route('/flickr/api/v1.0/user/<string:user_id>', methods=['DELETE'])
@app.route('/flickr/api/v1.0/users', methods=['POST'])
@app.route('/flickr/api/v1.0/albums/<string:user_id>', methods=['GET'])
@app.route('/flickr/api/v1.0/album/<string:user_id>/<string:album_id>', methods=['GET'])
@app.route('/flickr/api/v1.0/<string:image_type>/<string:user_id>/<string:album_id>/<string:photo_id>', methods=['GET'])


the frontend provides access to cached pictures, and allows for new users to be configured (and removed - along with their cached tweets)

thumbnails are 4-8kb in size

Sizes are:
Square
Large 1600
Small 320
Original
Large
Medium
Medium 640
Large Square
Medium 800
Small
Large 2048
Thumbnail

url provides a link to an 'all sizes' download page
source provides a link direct to the image at the given size

TODO:
* security
* some option to refresh the stream, provide configuration
* some tests
  - test with no internet connectivity
x stats - not possible without read of user info
* next and prev

