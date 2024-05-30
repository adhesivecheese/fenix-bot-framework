#!/usr/bin/env python3
from configparser import ConfigParser

import praw

from SubredditStream import MultiStream

config = ConfigParser()
config.read('config.ini')
CLIENT_ID = config["PRAW"].get("client_id")
CLIENT_SECRET = config["PRAW"].get("client_secret")
USER_AGENT = config["PRAW"].get("user_agent")
SUBREDDIT = config["PRAW"].get("subreddit")

"""
praw setup is as normal - you'll need a praw.Redit object, and you'll need a 
praw.reddit.subreddit object to feed to MultiStream.
"""
r = praw.Reddit(
	client_id=CLIENT_ID
	, client_secret=CLIENT_SECRET
	, user_agent=USER_AGENT
)
sub = r.subreddit(SUBREDDIT)

"""
Select the streams you wish to monitor here. Streams are checked in the order
they're presented in the list - if you wanted to check your modlog before you
checked submissions or edits, for example, you'd want to put "log" first.
"""
requested_streams = ["submissions","edited","log"]

"""
Certain streams (edited, spam, removed) might contain submissions or comments;
if you only wish to monitor one or the other, you can set that in parameters by
setting `only` to either `submissions` or `comments`. 
"""
params={
	"edited": {
		"only":"submissions"
	}
}
multistream = MultiStream(sub, stream_names=requested_streams, params=params)

"""
Internally, multiStream.streams will loop forever, yielding new items as they
become available - no need to wrap this in a `while True` loop.

multiStream.streams yields StreamItem items - the actual praw object is 
`StreamItem.item`; the other two attributes are `StreamItem.stream`, telling you
which stream the item originated from, and `StreamItem.kind`, which will tell 
you whether the item is a submission, comment, log, etc.
"""
for update in multistream.streams():
	if update.stream == "submissions":
		... # your code here
	elif update.stream =="edited":
		... # your code here
	elif update.stream == "log":
		... # your code here
