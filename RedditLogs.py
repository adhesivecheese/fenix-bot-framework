#!/usr/bin/env python3

from loguru import logger #Must be first import

from configparser import ConfigParser
from time import time
from datetime import datetime

config = ConfigParser()
config.read('config.ini')
SHOW_DELAY = config["LOGGING"].getboolean("Show_Delay", False)

class RedditLogs:
	"""
	Formatting for display of Reddit items to a logugu log

	Params
	------
	r : praw.Reddit
	show_delay : boolean
		whether to include the calculated delay between when an item was created
		and when it was picked up by the bot. Defaults to False.
	"""
	def __init__(self, r=None, show_delay=SHOW_DELAY):
		self.r = r
		self.show_delay = show_delay


	def __calc_delay(self, item_time):
		"""
		Calcualates the delay between when an item was created (or edited) and 
		the time it was picked up by the bot

		Params
		------
		item_time : int | float

		Returns
		-------
		str
		"""
		if not self.show_delay: return ""
		try:
			if self.show_delay:
					delay_time = int(time() - item_time)
					return f"(Delay: {delay_time}) "
			else: return ""
		except: return ("(unknown delay) ")


	def __get_author_name(self, item):
		"""
		get the item author's display name, if available, or else return `[deleted]`

		Params
		------
		item : praw.models.Comment | praw.models.Submission

		Returns
		-------
		str : the author's name
		"""
		try:
			name = item.author.name
			return f"/u/{name}"
		except AttributeError:
			return "[deleted]"


	def log_comments(self, item, log_kind="COMMENTS", delay=None, extra=None):
		"""
		Log message formatter Comments.

		Params
		------
		item : praw.models.Comment
		log_kind : str
			defaults to `COMMENTS`, but this logic is also used to display 
			comments in the SPAM, REMOVED, MODQUEUE, and EDITED messages.
		delay : str
			a string for the delay, if being calculated, for other logs that
			use this display logic
		extra : str
			used for displaying edit time.
		"""
		name = self.__get_author_name(item)
		# Reddit doesn't give us a convenient way to get the comment shortlink
		# format from what they provide, so we have to cook that up ourselves.
		permalink = item.link_permalink.split("comments/")[0]
		permalink += f"comments/{item.parent_id[3:]}/-/{item.id}"
		if not extra: extra = ""
		if not delay: delay = self.__calc_delay(item.created_utc)
		msg = f"{delay}{permalink} by {name}{extra}"
		logger.log(log_kind, msg)


	def log_submissions(self, item, log_kind="SUBMISSIONS", delay=None, extra=None):
		"""
		Log message formatter Submissions.

		Params
		------
		item : praw.models.Submission
		log_kind : str
			defaults to `SUBMISSIONS`, but this logic is also used to display 
			comments in the HOT, RISING, TOP, CONTROVERSIAL, UNMODERATED, SPAM, 
			REMOVED, MODQUEUE, EDITED messages.
		delay : str
			a string for the delay, if being calculated, for other logs that
			use this display logic
		extra : str
			used for displaying edit time.
		"""
		name = self.__get_author_name(item)
		if not delay: delay = self.__calc_delay(item.created_utc)
		if not extra: extra = ""
		msg = f"{delay}https://redd.it/{item.id} by {name}{extra}"
		logger.log(log_kind, msg)


	def log_hot(self, item):
		"""Log message formatter for hot"""
		self.log_submissions(item, log_kind="HOT")


	def log_rising(self, item):
		"""Log message formatter for rising"""
		self.log_submissions(item, log_kind="RISING")


	def log_top(self, item):
		"""Log message formatter for top"""
		self.log_submissions(item, log_kind="TOP")


	def log_controversial(self, item):
		"""Log message formatter for controversial"""
		self.log_submissions(item, log_kind="CONTROVERSIAL")


	def log_unmoderated(self, item):
		"""Log message formatter for unmoderated"""
		self.log_submissions(item, log_kind="UNMODERATED")


	def log_spam(self, item, kind):
		"""Log message formatter for spam."""
		if kind == "submissions":
			self.log_submissions(item, log_kind="SPAM")
		elif kind == "comments":
			self.log_comments(item, log_kind="SPAM")


	def log_removed(self, item, kind):
		"""Log message formatter for removed"""
		if kind == "submissions":
			self.log_submissions(item, log_kind="REMOVED")
		elif kind == "comments":
			self.log_comments(item, log_kind="REMOVED")


	def log_modqueue(self, item, kind):
		"""Log message formatter for modqueue"""
		if kind == "submissions":
			self.log_submissions(item, log_kind="MODQUEUE")
		elif kind == "comments":
			self.log_comments(item, log_kind="MODQUEUE")


	def log_edited(self, item, kind):
		"""Log message formatter for edited"""
		delay = self.__calc_delay(item.edited)
		if isinstance(item.edited, float):
			edit_time = datetime.fromtimestamp(item.edited)
		else:
			edit_time = item.edited
		if kind == "submissions":
			self.log_submissions(item, log_kind="EDITED", delay=delay, extra=f" (Post Edited @ {edit_time})")
		elif kind == "comments":
			self.log_comments(item, log_kind="EDITED", delay=delay, extra=f" (Comment Edited @ {edit_time})")


	def log_modmail_conversations(self, item):
		"""Log message formatter for modmail"""
		...


	def log_reports(self, item):
		"""Log message formatter for reports"""
		...


	def log_log(self, item):
		"""Log message formatter for modlog"""
		delay = self.__calc_delay(item.created_utc)
		actions = {
			"acceptmoderatorinvite":"accept moderator invite"
			,"add_community_topics":"add community topics"
			,"addcontributor":"add contributor"
			,"addmoderator":"add moderator"
			,"addremovalreason":"add removal reason"
			,"adjust_post_crowd_control_level":"adjust post crowd control level"
			,"approvecomment":"approve comment"
			,"approvelink":"approve post"
			,"banuser":"ban user"
			,"collections":"collections"
			,"community_status":"community status"
			,"community_styling":"style community"
			,"community_widgets":"widgets"
			,"create_award":"create award"
			,"create_scheduled_post":"create scheduled post"
			,"createremovalreason":"create removal reason"
			,"createrule":"create rule"
			,"delete_award":"delete award"
			,"delete_scheduled_post":"delete scheduled post"
			,"deletenote":"delete note"
			,"deleteoverriddenclassification":"delete overridden subreddit classification"
			,"deleteremovalreason":"delete removal reason"
			,"deleterule":"delete rule"
			,"dev_platform_app_changed":"app changed"
			,"dev_platform_app_disabled":"app disabled"
			,"dev_platform_app_enabled":"app enabled"
			,"dev_platform_app_installed":"app installed"
			,"dev_platform_app_uninstalled":"app uninstalled"
			,"disable_award":"disable award"
			,"disable_post_crowd_control_filter":"disable post crowd control filtering"
			,"distinguish":"distinguish"
			,"edit_post_requirements":"edit post requirements"
			,"edit_saved_response":"edit saved response"
			,"edit_scheduled_post":"edit scheduled post"
			,"editflair":"edit flair"
			,"editrule":"edit rule"
			,"editsettings":"edit settings"
			,"enable_award":"enable award"
			,"enable_post_crowd_control_filter":"enable post crowd control filtering"
			,"events":"events"
			,"hidden_award":"award hidden"
			,"ignorereports":"ignore reports"
			,"invitemoderator":"invite moderator"
			,"invitesubscriber":"invite subscriber"
			,"lock":"lock post"
			,"marknsfw":"mark nsfw"
			,"markoriginalcontent":"mark as original content"
			,"mod_award_given":"mod award given"
			,"modmail_enrollment":"enroll in new modmail"
			,"muteuser":"mute user"
			,"overrideclassification":"override subreddit classification"
			,"remove_community_topics":"remove community topics"
			,"removecomment":"remove comment"
			,"removecontributor":"remove contributor"
			,"removelink":"remove post"
			,"removemoderator":"remove moderator"
			,"removewikicontributor":"remove wiki contributor"
			,"reordermoderators":"reorder moderators"
			,"reorderremovalreason":"reorder removal reason"
			,"reorderrules":"reorder rules"
			,"setcontestmode":"set contest mode"
			,"setpermissions":"permissions"
			,"setsuggestedsort":"set suggested sort"
			,"showcomment":"show comment"
			,"snoozereports":"snooze reports"
			,"spamcomment":"spam comment"
			,"spamlink":"spam post"
			,"spoiler":"mark spoiler"
			,"sticky":"sticky post"
			,"submit_content_rating_survey":"submit content rating survey"
			,"submit_scheduled_post":"submit scheduled post"
			,"unbanuser":"unban user"
			,"unignorereports":"unignore reports"
			,"uninvitemoderator":"uninvite moderator"
			,"unlock":"unlock post"
			,"unmuteuser":"unmute user"
			,"unsetcontestmode":"unset contest mode"
			,"unsnoozereports":"unsnooze reports"
			,"unspoiler":"unmark spoiler"
			,"unsticky":"unsticky post"
			,"updateremovalreason":"update removal reason"
			,"wikibanned":"ban from wiki"
			,"wikicontributor":"add wiki contributor"
			,"wikipagelisted":"delist/relist wiki pages"
			,"wikipermlevel":"wiki page permissions"
			,"wikirevise":"wiki revise page"
			,"wikiunbanned":"unban from wiki"
		}
		if not item.target_fullname:
			link = None
		elif "t1_" in item.target_fullname:
			parent_id = item.target_permalink.split("comments/")[1].split("/")[0]
			link = f"https://reddit.com/comments/{parent_id}/-/{item.target_fullname[3:]}"
		elif "t2_" in item.target_fullname:
			link = f"/u/{item.target_author}"
		elif "t3_" in item.target_fullname:
			link = f"https://reddit.com/{item.target_fullname[3:]}"
   
		if item.action in ["approvelink","approvecomment"]:
			msg = f"{delay}/u/{item._mod} approved {link} by /u/{item.target_author}."
			if item.details: msg += f" ({item.details})"
		elif item.action in ["removelink", "removecomment"]:
			msg = f"{delay}/u/{item._mod} removed {link} by /u/{item.target_author}."
			if item.details: msg += f" ({item.details})"
		elif item.action in ["spamlink", "spamcomment"]:
			msg = f"{delay}/u/{item._mod} spammed {link} by /u/{item.target_author}."
			if item.details: msg += f" ({item.details})"
		else:
			msg = f"{delay}/u/{item._mod} performed action '{actions[item.action]}'"
			if link: msg += f" on {link}."
			if item.description: msg += f" Description: '{item.description}'."
			if item.details: msg += f" ({item.details})"
		logger.log("MODLOG", msg)
