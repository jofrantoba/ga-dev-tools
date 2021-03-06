# coding=utf-8

# Copyright 2018 Google Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This handler manages the server-side parts of the OAuth flow for the bitly
# API url. After a user authorizes us to use bitly, they are redirected here;
# this handler makes a request to turn the authorization code into a token.
# It then returns a special, empty HTML page. The javascript on that page
# uses the window.postMessage API to send the token back to the original
# URL page, then closes itself. This flow is mostly implemented by (at the
# time of this writing) a function called spawnWindowAndWait, which is in
# src/javascript/url-shortener.js.
#
# This handler specifically handles step 3 of bitly's OAuth web flow, documented
# here: https://dev.bitly.com/v4/#section/OAuth-Web-Flow

import urllib
import json
import copy

import webapp2

from google.appengine.api import urlfetch
from lib import bitly_api_credentials, template

def make_response(status, error=None, token=None, state=None):
	# NOTE: yes, this is very dissimilar to how the existing template system
	# is designed to be used. We want to use as much as the code as possible,
	# but the existing system is deeply tied to meta.yaml, and this page isn't
	# really a part of that whole system (since it's not a project page).
	data = {
		"site": {
			"token": token,
			"error": error,
			"state": state,
		}
	}

	return webapp2.Response(
		status=status,
		content_type='text/html',
		body=template.render(
			project='bitly-api-token-handler',
			template_data=data
		)
	)


# TODO(nathanwest): Replace the local file containing the secret key with
# something more durable, like Google Cloud Key Management Service.
# TODO(nathanwest): Add logging to this thing
class UrlShortenAuthHandler(webapp2.RequestHandler):
	def get(self):
		# Per the bitly docs: When we arrive at this URL, it is with a code and
		# a state. The code is needed for auth flow.

		# Technically incorrect, as .params examines a form-encoded body in
		# addition to the ? parameters, but it shouldn't matter in practice
		try:
			auth_code = self.request.params.getone('code')
		except KeyError as e:
			return make_response(
				status=400,
				error="No access code provided; was permission denied?",
			)
		state = self.request.params.get('state')

		# Unfortunately, there doesn't seem to be a way to do "real" async at
		# this time. urlfetch has made some motions in that direction, but it
		# still blocks this function until completion.

		client_id = bitly_api_credentials.CLIENT_ID
		client_secret = bitly_api_credentials.CLIENT_SECRET

		try:
			auth_response = urlfetch.fetch(
				url="https://api-ssl.bitly.com/oauth/access_token",
				method='POST',
				payload=urllib.urlencode({
					'client_id': client_id,
					'client_secret': client_secret,
					'code': auth_code,
					'redirect_uri': self.request.path_url,
				}),
				headers={
					'Content-Type': "application/x-www-form-urlencoded",
					'Accept': 'application/json'
				},
				validate_certificate=True,
				follow_redirects=True,
			)

		except Exception as e:
			return make_response(
				status=500,
				error="Error getting an access token from bitly",
			)

		if auth_response.status_code >= 300:
			return make_response(
				status=500,
				error="Error: bitly returned error code {} instead of a token"
					.format(auth_response.status_code),
			)

		auth_body = json.loads(auth_response.content)

		# This response body includes the Javascript that will forward the
		# token and state to the client via postMessage
		return make_response(
			status=200,
			token=auth_body['access_token'],
			state=state
		)
