#!/usr/bin/env python3

import praw

from SubredditStream import MultiStream

"""
praw setup is as normal - you'll need a praw.Redit object, and you'll need a 
praw.reddit.subreddit object to feed to MultiStream.
"""
r = praw.Reddit(
	client_id="my client id"
	, client_secret="my client secret"
	, user_agent="my user agent"
)
sub = r.subreddit("my_subreddit")

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
