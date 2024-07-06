#!/usr/bin/env python3

import pickle
from collections import OrderedDict
from configparser import ConfigParser
from pathlib import Path
from random import random, randint
from time import sleep, time

import praw.models.reddit as praw_models
from prawcore.exceptions import (
	BadRequest, ResponseException, ServerError, RequestException
)

from bot_logging import logger
from RedditLogs import RedditLogs


"""
Variables used here are stored in config.ini. All variables have defaults, in 
the event that any given item does not appear in the config.ini file.
"""
config = ConfigParser()
config.read('config.ini')

EDIT_FETCH_ATTEMPTS = config["STREAMS"].getint("Edit_Fetch_Attempts", 3)
EXCEPTION_PAUSE = config["STREAMS"].getint("Exeption_Pause", 60)
LOG_STREAMS = config["LOGGING"].getboolean("Log_Streams", True)
#Effects ExponentialCounter
RATELIMIT_EXHAUSTION = config["LOGGING"].getboolean("Ratelimit_Exhaustion", True)
MIN_WAIT = config["STREAMS"].getint("Min_Wait", 1)
MAX_WAIT = config["STREAMS"].getint("Max_Wait", 16)
#Effects PerformanceCounter
SAFETY_THRESHOLD = config['STREAMS'].getfloat("Safety_Factor", 0.9)


class PerformanceCounter:
	"""
	A counter designed to induce minimal delay in checking streams while still
	respecting API usage limits.

	PerformanceCounter is designed to automatically adjust the rate at which new
	fetches from reddit are performed, based on the number of calls available.
	By default, this class will attempt to use 90% of available calls in a 
	given reset period, with 10% left as reserve, in case there's a spike in 
	activity. The threshold is adjustable by setting `Safety_Factor` in the
	`STREAMS` section of config.ini.

	As both remaining calls and cooldown seconds are relayed to us by Reddit,
	multiple instances of this bot can coexist and should automatically 
	adjust their rate-limiting to stay under limits.

	Parameters
	----------
	reddit : praw.Reddit
	ratelimit_requests : int
		API calls allowed by Reddit in a given timeframe
	ratelimit_cooldown : int
		Seconds between API ratelimit resets
	"""
	def __init__(self, reddit=None, ratelimit_requests=1000, ratelimit_cooldown=600):
		self.reddit = reddit
		self.safety_threshold = SAFETY_THRESHOLD
		self.ratelimit_requests = ratelimit_requests
		self.target_requests = int(ratelimit_requests * SAFETY_THRESHOLD)
		self.ratelimit_cooldown = ratelimit_cooldown
		self.min_wait = (ratelimit_cooldown / ratelimit_requests) / SAFETY_THRESHOLD
		self.current_wait = self.min_wait
		self.next_reset_time = 0
		self.last_time = time()
		# These do nothing, and only exist for compat with ExponentialCounter
		self.incremented = False 
		self.empty_responses = 0
		self.value = 0


	def increment(self): return # compatibility with ExponentialCounter
	def reset(self): return # compatibility with ExponentialCounter


	def jitter(self):
		"""
		introduce a random small delay based on the current wait
		"""
		max_jitter = self.current_wait / 16
		return abs(random()*max_jitter - max_jitter/2)


	def end_loop(self):
		"""
		Calculate the pause between checking streams to keep us on target to hit
		the specified API usage.
		
		This method differentiates between "safe" API calls - calls when we 
		haven't hit our target usage, and "reserve" API calls - calls used in
		excess of the target usage we're aiming for.
		"""
		now = time()
		reset_timestamp = self.reddit.auth.limits['reset_timestamp']
		last_run_duration = now - self.last_time - self.current_wait
		self.last_time = now
		time_remaining = reset_timestamp - now
		time_elapsed = self.ratelimit_cooldown - time_remaining

		calls_used = int(self.reddit.auth.limits['used'])
		calls_remaining = self.target_requests - calls_used
		
		# Allow us to dip into reserve calls if we've exhasted our normal
		# calls. This should probably be a configurable setting?
		if calls_remaining <= 0:
			calls_remaining = self.ratelimit_requests - calls_used
			if calls_remaining > 10:
				msg = f"Exhausted Safe Calls. {calls_remaining} left in reserve"
				msg += f" for the next {time_remaining} seconds."
				logger.warning(msg)
			else:
				msg = "Reserve calls exhausted (<10 API calls remain)"
				msg += f" for the next {time_remaining} seconds. Sleeping "
				msg += "until next API ratelimit reset." 
				logger.warning(msg)
				sleep(time_remaining)
				return


		self.current_wait = (
			(time_remaining / calls_remaining) / self.safety_threshold
			) + last_run_duration

		# These calculate the calls per second since the last reset, and what
		# the future usage needs to be to hit our target; these should stay
		# as close to balanced as possible.
		current_usage_rate = calls_used / time_elapsed
		future_usage_rate = calls_remaining / time_remaining

		if current_usage_rate > future_usage_rate:
			self.current_wait += last_run_duration

		# a bit of jitter so we're not ever hitting the API at a fixed interval
		self.current_wait = self.current_wait + abs(self.jitter())

		# There's never a need to wait longer than our next reset.
		if self.current_wait > time_remaining:
			self.current_wait = time_remaining

		# Don't ever wait less time than the minimum wait time. There are 
		# certain situations that this might mean we don't use all our calls 
		# (say, if a couple loops take an inordinantly long time to run)
		# but better to undershoot than overshoot.
		if self.current_wait < self.min_wait:
			self.current_wait = self.min_wait

		msg = f"Current CPS Rate: {current_usage_rate:0.3f} | "
		msg += f"Future CPS Rate: {future_usage_rate:0.3f} | "
		msg += f"calls remaining: {calls_remaining} | "
		msg += f"next reset: ~{time_remaining:0.0f} seconds | "
		msg += f"Sleeping: ~{self.current_wait:0.3f} seconds"
		logger.debug(msg)

		sleep(abs(self.current_wait))


class ExponentialCounter:
	"""
	A counter designed for checking multiple streams with exponential backoff if
	no new items are detected.

	ExponentialCounter is adapted from code found in PRAW 7.7.1. This version 
	of the counter employs additional class methods to facilitate sharing one 
	counter between multiple streams.

	ExponentialCounter is less performant than PerformanceCounter, and is 
	included for cases where minimizing network requests is more important than 
	timely updates from Reddit.

	Parameters
	----------
	max_counter : int
		The maximum number of seconds that ExponentialCounter will pause 
		between loops.
	reddit : praw.Reddit
	"""
	def __init__(self, max_counter=MAX_WAIT, reddit=None):
		self._base = MIN_WAIT
		self._max = max_counter
		self.incremented = False
		self.value = MIN_WAIT
		self.empty_responses = 0
		self.reddit = reddit
		self.throttle_level = MAX_WAIT


	def increment(self):
		"""
		This method will increment the counter exponentially up to the 
		maximum value, provided that another stream has not already 
		incremented the counter since a reset of the counter has been called.
		"""
		self.incremented = True
		max_jitter = self._base / MAX_WAIT
		jitter = random()*max_jitter - max_jitter / 2
		if self.throttle_level == MAX_WAIT:
			self.value = self._base + jitter
		else:
			self.value = self.throttle_level + jitter
		self._base = min(self._base * 2, self._max)


	def reset(self):
		"""Reset the counter"""
		self._base = MIN_WAIT
		max_jitter = self._base / MAX_WAIT
		self._value = MIN_WAIT + random()*max_jitter - max_jitter / 2
		self.incremented = False
		self.empty_responses = 0
		self.throttle_level = MAX_WAIT


	def end_loop(self):
		"""Reset the streams for next run, pause for the specified delay"""
		self.incremented = False
		logger.debug(f"Sleeping for ~{self.value:0.3f} seconds")
		sleep(self.value)
		self._calculate_ratelimit_used()


	def _calculate_ratelimit_used(self):
		"""
		This method can perform additional throttling in the event of heavy API 
		usage in an attempt to prevent the bot from overshooting the API limit 
		restrictions.

		Values in this method are hard-coded to the current (as of 2024-05-29) 
		API restrictions of 1000 calls in 600 seconds.
		"""
		if self.reddit == None: return
		now = int(time())
		reset_timestamp = int(self.reddit.auth.limits['reset_timestamp'])
		next_reset = reset_timestamp-now
		elapsed = 600 - next_reset
		used = self.reddit.auth.limits['used']
		remaining = self.reddit.auth.limits['remaining']
		if int(used) != 0:
			usage_rate = float(f"{used/elapsed:0.1f}")
			used_pct = float(f"{(used/remaining)*100:0.1f}")
		else:
			usage_rate = 0
			used_pct = 0
		msg = f"Bot has used {used_pct}% of the ratelimit in the last "
		msg += f"{elapsed} seconds. (Avg Requests: {usage_rate}/second)"
		logger.debug(msg)
		if usage_rate > 1.67 and remaining > 30:
			msg = f"Excessive API usage ({usage_rate}/second avg > 1.67/second "
			msg += "avg. Increasing interval between requests by 1.2x to "
			msg += f"{self.throttle_level} seconds until ratelimit reset. "
			logger.warning(msg)
			self.throttle_level = self.throttle_level*1.2
		elif usage_rate < 1.67 and self.throttle_level > MAX_WAIT:
			self.throttle_level = MAX_WAIT
			msg = f"Usage rates returned to sustainable levels ({usage_rate}"
			msg += "/second). Restoring normal request intervals."
			logger.info()
		elif remaining < RATELIMIT_EXHAUSTION:
			msg = f"Ratelimit functionally exhausted (remaining < "
			msg += f"{RATELIMIT_EXHAUSTION}). Sleeping for {remaining+1} "
			msg += "seconds until past ratelimit reset time."
			logger.warning(msg)
			sleep(remaining+1)


class BoundedSet:
	"""
	A set with a maximum size that evicts the oldest items when necessary.
	This class does not implement the complete set interface.

	Note
	----
	This class is basically just straight praw code, taken from 7.7.1. 
	"""
	def __contains__(self, item):
		"""Test if the :class:`.BoundedSet` contains item."""
		self._access(item)
		return item in self._set


	def __init__(self, max_items=1001):
		"""Initialize a :class:`.BoundedSet` instance."""
		self.max_items = max_items
		self._set = OrderedDict()


	def _access(self, item):
		if item in self._set:
			self._set.move_to_end(item)


	def add(self, item):
		"""Add an item to the set discarding the oldest item if necessary."""
		self._access(item)
		self._set[item] = None
		if len(self._set) > self.max_items:
			self._set.popitem(last=False)


	def remove(self, item):
		"""Remove an item by it's attribute from the set."""
		if item in self._set:
			self._access(item)
			self._set.popitem(last=True)


	def empty(self):
		"""Empty the current set."""
		self._set = OrderedDict()


	def __len__(self):
		"""Enable usage of len() to determine the number of items in a set."""
		return len(self._set)


	def __getitem__(self, key):
		"""allows instances of this method to use the [] (indexer) operators"""
		return list(self._set)[key]


class StreamItem:
	"""
	StreamItem is a wrapper class for a praw object, which returns the object, 
	as well as the stream it originated from and the object kind (submissions,
	comments, logs, etc)

	Parameters
	----------
	stream : str
		The name of the stream that produced this item
	item : praw object
		the praw object generated by the stream
	"""
	def __init__(self, stream, item):
		self.stream = stream
		self.item = item
		self.kind = self.determine_kind(item)


	def determine_kind(self, item):
		"""
		used to set the object kind. As certain streams (edited, spam, removed) 
		may yield either submissions or comments, this helps determine the 
		object kind so that higher-level bot functions don't need to sort that 
		out on their own.
		"""
		if isinstance(item, praw_models.comment.Comment):
			return "comments"
		elif isinstance(item, praw_models.submission.Submission):
			return "submissions"
		else: return self.stream


	def __repr__(self):
		msg = f"StreamItem(stream='{self.stream}', item='{self.item}'"
		msg += f", kind='{self.kind}')"
		return msg


class MultiStream:
	"""
	MultiStream is a one-stop shop for building and running multiple streams for 
	a single subreddit.

	Parameters
	----------
	sub : praw.Subreddit
		the subreddit to monitor streams for.
	counter : None | class object 
		counter defaults to a PerformanceCounter, but you can set an instance of
		ExponentialCounter here, or create your own custom counter
	stream_names : list
		a list containing one or more stream names to build. Valid stream names
		may be found in SubredditStream._get_listing
	params : dictionary
		used for passing parameters to streams. For example, to only monitor 
		edited submissions, ignorning comments, params	would be 
		`{"edited":{"only":"submissions"}}`
	"""
	def __init__(self, sub, counter=None, stream_names=[], params={}):
		self.sub = sub
		if counter:
			self.counter = counter
		else:
			self.counter = PerformanceCounter(reddit=self.sub._reddit)
		self.stream_names = stream_names
		self.params = params
		self.stream_objects = {}
		self.stream_generators = {}
		self.build_streams()
		self.log_formatter = RedditLogs()


	def build_streams(self):
		"""builds the requested streams from self.stream_names"""
		for stream in self.stream_names:
			if stream in self.params.keys(): params = self.params[stream]
			else: params = {}
			self.stream_objects[stream] = SubredditStream(
				stream
				, sub=self.sub
				, counter=self.counter
				, params=params
			)
		for stream in self.stream_objects.values():
			self.stream_generators[stream] = stream.stream(raise_errors=True)


	def shutdown(self):
		"""perform a clean shutdown of streams, saving positions."""
		for stream in self.stream_objects.values():
			stream._save_seen_attributes()


	def rebuild_streams(self):
		"""
		Tear down and recreate streams in the event of problems with one or 
		more streams during the running of the bot.
		"""
		self.shutdown()
		try:
			self.stream_objects = {}
			self.stream_generators = {}
			self.build_streams()
			logger.info("Rebuilt Streams.")
		except Exception as e:
			logger.opt(exception=True).critical(f"Failed to rebuild Streams:")
			raise e


	def log_streams(self, item):
		"""
		Pass items to a log formatter for appropriate logging. Logging every
		item that passes through the stream may be turned off by setting 
		`Log_Streams` to False in the `[LOGGING]` section of config.ini
		"""
		if item.stream == "submissions":
			self.log_formatter.log_submissions(item.item)
		elif item.stream == "comments":
			self.log_formatter.log_comments(item.item)
		elif item.stream == "edited":
			self.log_formatter.log_edited(item.item, item.kind)
		elif item.stream == "spam":
			self.log_formatter.log_spam(item.item, item.kind)
		elif item.stream == "log":
			self.log_formatter.log_log(item.item)
		elif item.stream == "modqueue":
			self.log_formatter.log_modqueue(item.item, item.kind)


	def streams(self):
		"""
		streams runs multiple streams set up on instantiating an instance of
		multistream, yielding items as they become available, and rebuilding 
		streams as necessary.
		"""
		logger.info("MultiStream streams starting!")
		while True:
			try:
				for stream in self.stream_generators.values():
					for item in stream:
						if item is None:
							# if the stream is done yielding items, we break so 
							# that we can move on to the next stream
							break
						if LOG_STREAMS:
							# log stream items to the console and file, if enabled
							self.log_streams(item)
						if (
							item.stream == "log"
							and	"modqueue" in self.stream_objects.keys()
							and item.item.action in [
								"approvelink", "removelink", "spamlink"
								, "approvecomment", "removecomment"
								, "spamcomment"
							]
						):
							# if we're monitoring the modqueue stream, remove 
							# actioned items from seen items in the modqueue 
							# stream to prevent excess full fetches.
							self.stream_objects['modqueue'].remove_seen_attribute(
								item.item.target_fullname
							)
							msg = f"Removed '{item.item.target_fullname}' "
							msg += "from modqueue stream seen items."
							logger.debug(msg)
						yield item
				self.counter.end_loop()
			except ResponseException as e:
				msg = f"Caught praw ResponseException: '{str(e)}'. Attempting "
				msg += f"to continue in {EXCEPTION_PAUSE} seconds..."
				logger.error(msg)
				sleep(EXCEPTION_PAUSE)
				logger.info("MultiStream streams restarting!")
				self.rebuild_streams()
			except RequestException as e:
				msg = f"Caught praw RequestException: '{str(e)}'. Attempting "
				msg += f"to continue in {EXCEPTION_PAUSE} seconds..."
				logger.error(msg)
				sleep(EXCEPTION_PAUSE)
				logger.info("MultiStream streams restarting!")
				self.rebuild_streams()
			except ServerError as e:
				msg = f"Caught praw ServerError: '{str(e)}'. Attempting to "
				msg += f"continue in {EXCEPTION_PAUSE} seconds..."
				logger.error(msg)
				sleep(EXCEPTION_PAUSE)
				logger.info("MultiStream streams restarting!")
				self.rebuild_streams()
			except Exception:
				logger.opt(exception=True).critical(f"Unhandled Error:")

class SubredditStream:
	"""
	A single self-healing, position-saving stream of a Reddit listing for a
	subreddit.

	a SubredditStream instance will save seen items (up to 1000, the max number
	of items that can be fetched from the API) to disk, in a folder named 
	`.cache-<subreddit_name>`, where `<subreddit_name>` is the display name of 
	your subreddit. This allows saving the stream's position across restarts 
	of the bot. 

	Parameters
	----------
	stream_name | str
		the name of a listing you wish to generate a stream for. Available 
		streams are found in SubredditStream._get_listing
	sub | praw.Subreddit
		the praw.Subreddit object corresponding to the subreddit you want to 
		monitor
	counter | A Counter Object
		Defaults to PerformanceCounter. You can also use ExponentialCounter, or
		a custom implementation
	wait_for_edit | int
		if set to a positive value, will attempt to fetch an edit a set number 
		of times before giving up. More explination in the docstring for 
		`SubredditStream.__get_edit_time`
	params | dict
		a dictionary of parameters to pass to a stream; for example, to only 
		fetch comments, one would pass `{'only':'comments'}`

	Note
	----
	Here be dragons. SubredditStream replaces praw's listingGenerator with a 
	custom implementation integrated into the generator; in practice, this means
	that a SubredditStream doesn't look much like a normal praw object.
	"""
	def __init__(
			self
			, stream_name
			, sub=None
			, counter=PerformanceCounter()
			, wait_for_edit=EDIT_FETCH_ATTEMPTS
			, params = {}
		):
		self.stream_name = stream_name.lower()
		self.subreddit = sub
		self._location_base = f".cache-{self.subreddit.display_name}"
		self._save_location = f"{self._location_base}/{self.stream_name}.pkl"
		self._counter = counter
		self._seen_attributes = self.__load_seen_attributes()
		self._listing = self._get_listing()
		self._wait_for_edit = wait_for_edit
		self.params = params
		self.stream_alive = True


	def remove_seen_attribute(self, attribute):
		"""remove an item from the listing of seen items"""
		self._seen_attributes.remove(attribute)


	def _save_seen_attributes(self):
		"""
		Saves Seen Items to a file.

		This method saves seen items to a file to persist a stream's 
		position across reboots of the software. Files are saved to
		".Stream" directory, located in the same directory this
		file is run from. File is saved as `<sub>-<kind>-seen_attributes.pkl`.
		
		For example, for a Stream monitoring the "submissions" stream on 
		subreddit "test", the resulting output file would be 
		"test-submissions-seen_attributes.pkl"

		"""
		# Ensure our save directory exists
		try: Path(self._location_base).mkdir(exist_ok=True)
		except: return
		# `wb` for "Write Bytes" - pickle objects are bytes not strings
		with open(self._save_location, "wb") as output_file:
			pickle.dump(self._seen_attributes, output_file)


	def __load_seen_attributes(self):
		"""
		Loads Seen Items from a file.

		This method loads seen items from a file to persist a stream's 
		position across reboots of the software. Files are saved to the
		".Stream" directory, located in the same directory this
		file is run from. File is saved as `<sub>-<kind>-seen_attributes.pkl`.
		For example, for a RedditStream monitoring the "submissions" 
		stream on subreddit "test", the resulting output file would be 
		"test-submissions-seen_attributes.pkl"
		"""
		try:
			with open(self._save_location, "rb") as input_file:
				return pickle.load(input_file)
		except:
			return BoundedSet(1001)


	def _get_listing(self, wikipage=None, timeframe="All"):
		"""
		Generates a listing for use in the generator.

		Parameters
		----------
		wikipage : None | str
			used to specify a wikipage to stream; this should be the name of the
			page you wish to stream.
		timeframe : str
			the timeframe to fetch items from for Top & Controversial

		Returns
		-------
		ListingGen | dict
			a ListingGen is a dictionary with two items; the `attribute` to 
			store for the given stream (usually the fullname, though sometimes
			other attributes for some streams), and a `source`, which is the 
			praw listing for the thing you want to monitor for a given subreddit.

		Note
		----
		Generally, listings behave the same way that they do in a vanilla praw
		instance; there are a few special cases:
		* `edited` stores the fullname AND edit time, allowing capture of 
		  multiple edits.
		* `spam` will *only* return items that are actually spam, not all 
		  removed items regardless of whether they're actually spam or not. For
		  vanilla-praw behavior, use `removed` instead of `spam`; `removed` will
		  list all removed items (what you see on r/yoursubreddit/about/spam) 
		  regardless of their spam status
		"""
		listingGen = {
			"attribute":"fullname"
		}
		if self.stream_name == "comments":
			listingGen["source"] = self.subreddit.comments
			return listingGen
		elif self.stream_name == "controversial":
			# TODO Currently this will only stream all-time controversial
			listingGen["source"] = self.subreddit.controversial
			return listingGen
		elif self.stream_name == "edited":
			# Edited uses a tuple of fullname and edit time to store whether an
			# edit has been seen or not; this allows the bot to capture multiple
			# edits of a single comment or submission.
			listingGen["source"] = self.subreddit.mod.edited
			listingGen["attribute"] = "edited" # tuple([fullname, edited])
			return listingGen
		elif self.stream_name == "hot":
			listingGen["source"] = self.subreddit.hot
			return listingGen
		elif self.stream_name == "log":
			listingGen["source"] = self.subreddit.mod.log
			listingGen["attribute"] = "id"
			return listingGen
		elif self.stream_name == "modmail_conversations":
			listingGen["source"] = self.subreddit.modmail.conversations
			listingGen["attribute"] = "id"
			return listingGen
		elif self.stream_name == "modqueue":
			listingGen["source"] = self.subreddit.mod.modqueue
			return listingGen
		elif self.stream_name == "reports":
			listingGen["source"] = self.subreddit.mod.reports
			# TODO: Generate an attribute profile that allows for storing 
			# reports that might come in after an initial report
			return listingGen
		elif self.stream_name == "rising":
			listingGen["source"] = self.subreddit.rising
			return listingGen
		elif self.stream_name == "spam" or self.stream_name == "removed":
			listingGen["source"] = self.subreddit.mod.spam
			return listingGen
		elif self.stream_name == "submissions":
			listingGen["source"] = self.subreddit.new
			return listingGen
		elif self.stream_name == "top":
			# TODO Currently this will only stream all-time top
			listingGen["source"] = self.subreddit.top
			return listingGen
		elif self.stream_name == "unmoderated":
			listingGen["source"] = self.subreddit.mod.unmoderated
			return listingGen
		#TODO: Wikipage Stream, which isn't implemented by praw


	def __is_actually_spam(self, item):
		"""
		Check whether an item's actually spam or just removed.

		The "spam" queue is actually a queue of ALL	removed items, whether 
		they've been removed as spam or not. Returns `True` if an item was actually
		removed as spam, and `False` if an item was just removed normally.

		Parameters
		----------
		item : praw.submission | praw.comment
	
		Returns
		-------
		Bool : `True` if an item was removed as spam, else `False`.
		"""
		try:
			# Reddit weirdly uses the "ban_note" field for the removal kind,
			# instead of "details" or something else. This is weird because a 
			# spam removal categorically NOT a ban.
			if (
				"spam" in item.ban_note and
				"not" not in item.ban_note
			):
				return True
			else:
				return False
		except:
			return False


	def __get_edit_time(self, item):
		"""
		Attempt to fetch an edit if an item is indicated to be edited.

		Sometimes items wind up in an edited queue before the content of the 
		edit actually propogates to the JSON listing. If that's the case, 
		calling `item._fetch()` will perform a fetch on the item to ensure we 
		have the updated information. On failing to get an updated item, this 
		method will sleep for 1 second and then attempt to fetch it again, up
		to the number of times specified by `EDIT_FETCH_ATTEMPTS`, found in
		config.ini (defaults to 1 attempt).
		"""
		if self._wait_for_edit > 0:
			fetch_tries = 0
			while not item.edited and fetch_tries <= self._wait_for_edit:
				item._fetch()
				fetch_tries += 1
				if not item.edited: sleep(1)
		return item


	def __generator(
			self
			, listingGen=None
			, raise_errors=False
			, max_time_before_full_fetch = 60
			, **kwargs
		):
		"""
		The generator fuction that fetches items from Reddit and yields them as 
		they become available.

		Parameters
		----------
		listingGen : None | dict
			a dictionary (generated by `SubredditStream._get_listing`) giving
			the source of the stream, as well as the attribute to store for 
			position-keeping. Ordinarily, this is created by instantiating a 
			SubredditStream object, but you can also pass a custom listing if
			a subreddit endpoint you want to stream isn't listed.
		raise_errors : bool
			if set to False, the stream will attempt to sleep before continuing 
			without raising an error. If set to True, will raise errors to be
			handled further up the chain.
		max_time_before_full_fetch : int
			Perform a full fetch of up to 100 items from the target endpoint if
			no new items have been yielded in the last number of seconds set by
			this variable. This is a kludgey fix for dumb behavior in the Reddit
			API. If you attempt to fetch new items after a deleted item, instead
			of throwing an error, Reddit will just return empty listings 
			forever instead of doing an intelligent thing like notifying you 
			the item wasn't found, or returning items after the deleted item 
			(since the API would know when that item was created, even if it's
			deleted). 
		**kwargs : dict
			a dictionary of additional parameters to pass to the stream.

		Yields
		------
		praw objects - submissions, comments, modlog items, modmail, spam, etc.

		Note
		----
		I will be perfectly honest, I'm writing documentation after the fact, 
		and I honestly don't rememebr why there are seperate `__generator()` and 
		`stream()` methods. I'm certain I had a reason, and it's PROBABLY a good
		one, but I'll be damned if I can remember what that was and I'm too much
		of a coward right now to try renaming this `stream()` and figuring out 
		what (if anything) breaks.
		"""
		def __attribute_yielded(item):
			"""
			determine whether an item has already been yielded or not.
			Returns `True` if item has been yielded, else `False`.
			"""
			fetch_attribute = listingGen['attribute']
			if fetch_attribute == "edited":
				item = self.__get_edit_time(item)
				fullname = getattr(item, "fullname")
				edited = getattr(item, "edited")
				attribute = tuple([fullname, edited])
			else:
				attribute = getattr(item, fetch_attribute)
			if attribute not in self._seen_attributes: return attribute
			else: return True

		if not listingGen: listingGen = self._listing
		praw_listing = listingGen['source']

		limit = 100 # max number of items that can be yielded at one time

		params = {}
		# add params from the Class
		for key, value in self.params.items(): params[key] = value
		# add/modify params passed as keyword arguments
		for key, value in kwargs.items(): params[key] = value

		# prime the last item time with the current time. Used to determine 
		# whether a full fetch is neccesary.
		last_item_time = time()

		# Submissions are called links as far as the API is concerned
		if "only" in params.keys():
			if params["only"] == "submissions":
				params["only"] = "links"

		# this is the main loop that generates items
		while True:
			# This will only run if raise_errors is set to `False`
			if self.stream_alive == False:
				logger.info(f"rebuilding listing for {self.stream_name}")
				self._listing = self._get_listing()
				praw_listing = self._listing['source']
				self.stream_alive = True

			has_found_items = False
			if len(self._seen_attributes) == 0:
				before = None
			elif len(self._seen_attributes) == 1:
				before = self._seen_attributes[0]
			elif time() - last_item_time > max_time_before_full_fetch:
				before = None
				last_item_time = time()
				msg =  f"longer than {max_time_before_full_fetch} since last "
				msg += f"yield on {self.stream_name}, doing full fetch"
				logger.debug(msg)
			else:
				# if we have multiple attributes, randomly fetch either the 
				# most recent or the one before that, to help prevent unneeded
				# full fetches if the most recent item has gone away.
				max_attribute = len(self._seen_attributes) - 1
				min_attribute = max_attribute - 2
				before_list = [min_attribute, max_attribute]
				before_list.sort()
				before_index = randint(before_list[0],before_list[1])
				before = self._seen_attributes[before_index]
				if isinstance(before, list): before = before[0]

			# Fetch from Reddit
			try:
				params['before'] = before
				items = list(praw_listing(limit=limit, params=params))
			except KeyboardInterrupt:
				raise KeyboardInterrupt
			except GeneratorExit:
				return
			except BadRequest:
				msg = f"Got Bad Request from Reddit. Removing '{before}'"
				msg += "from seen attributes"
				logger.debug(msg)
				self.remove_seen_attribute(before)
				items = list(praw_listing(limit=limit))
			except Exception as e:
				if raise_errors:
					raise e
				else:
					self.stream_alive = False
					msg = f"Caught praw RequestException. Attempting "
					msg += f"to continue in {EXCEPTION_PAUSE} seconds..."
					logger.error(msg)
					sleep(EXCEPTION_PAUSE)

			# Reddit listings are from newest to oldest; we need to reverse this
			# so that we're yielding items chronologically.
			items.reverse()

			# Yield found items
			for item in items:
				# Check if items' already been yielded; if so, don't yield again
				attribute = __attribute_yielded(item)
				if attribute == True:
					continue
				has_found_items = True
				self._seen_attributes.add(attribute)
				if self.stream_name == "spam":
					if not self.__is_actually_spam(item): continue
				last_item_time = time()
				yield StreamItem(self.stream_name, item)

			# We yield `None` when the stream is exhausted, so we can indicate
			# that we're ready to check the next stream (if running multiple)
			# if ExponentialCounter ever goes away, we can replace the next 7 
			# lines with a single `yield None`; the counter stuff is just for 
			# the legacy counter.
			if has_found_items:
				self._counter.reset()
				yield None
			else:
				if not self._counter.incremented:
					self._counter.increment()
				yield None

			# Try to avoid caches by fetching a random number of items each time
			limit = randint(90, 100)


	def stream(self, **kwargs):
		"""
		wrapper for private function __generator. Call this to actually run 
		the stream.
		"""
		return self.__generator(**kwargs)
