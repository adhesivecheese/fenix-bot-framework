# fenix-bot-framework

The fenix-bot-framework is a generic framework for building a subreddit moderation bot for Reddit. It is built upon PRAW, and uses loguru for logging, and provides multiple useful features for building moderation bots.

## Quickstart

This quickstart guide assumes you already have a script-type app configured with Reddit; if you don't, see the [praw documentation](https://github.com/reddit-archive/reddit/wiki/OAuth2-Quick-Start-Example#first-steps) for instructions for creating one

1. Download and unzip this repository, navigate to the repository folder
2. (optional) Create a python3 virtual enviornment: `python3 -m venv .venv`, and activate it with `source .venv/bin/activate`
3. Install requirements (praw and loguru) `pip install -r requirements.txt`
4. Copy or rename `config.ini.example` to `config.ini`; make adjustments as desired. (Don't forget to fill out the [PRAW] section!)
5. Start your new bot with `python3 multiStream_example_bot.py` to begin logging!

## Genesis and Rationale

It is common for a subreddit moderation bot to need to monitor multiple sources - submissions, comments, the modlog, etc. The general recommendation is to either run multiple bots, one monitoring each stream, or if that's not practical, to use a loop to cycle through streams. Frequently, however, neither of these approaches is ideal. If running multiple bots per stream, you have additional overhead coordinating actions between streams. If using the loop example, you can deal with long delays between loops through the streams, as each stream has it's own wait-limit before attempting to fetch new items. And then there's stream reliability to contend with - PRAW's streams can be fragile, and tearing down and recreating a stream on an error (IF the stream errors out at all, and doesn't just silently fail) means you have to deal with duplicate items yielded from recreating the streams. The fenix-bot-framework is designed to solve these problems. 

Initially, the goal of the project that eventually became this framework was simply to write a more robust stream implementation - streams that can handle bad requests, that can tell whether they're alive or dead and recreate themself at need, and streams that remember their place across Reddit outages or bot restarts. Streams that can share a counter, removing potential bottlenecks for waits if one of the streams you're monitoring is less active than others. The `SubredditStream` class can handle all these, and do it with ease.

Enabling sharing of a counter between multiple streams required modifications to praw's built-in `ExponentialCounter` (the counter used to determine the time a stream should sleep between checks). This fairly quickly lead me to dissatisfaction with the PRAW approach - even with sharing a counter, you can still routinely run into a delay of 10+ seconds actioning new items, with plenty of available API calls left on the table. This led to the creation of a new counter, `PerformanceCounter`. `PerformanceCounter` is designed to check streams as often as possible while remaining under a user-defined percentage of the available ratelimit (by default aiming to use as close to 90% of available API calls in any given reset period). It does this in a usage-aware way, tuning the wait between fetches from the API to account for additional usage from the currently running bot, or any other bot's running under the same account. When configured to check 5 different streams and without additional calls needed for moderation actions, streams using a PerformanceCounter typically deliver new items from the API in under 1 second from the time they appear in the API.

Tying these two items together is `MultiStream` - a class which can build (and optionally run, with `MultiStream.stream()`) multiple streams using `SubredditStream` and `PerformanceCounter`. `MultiStream.stream()` allows you not have to worry about setting up your own boilerplate and error handling for building a bot, and allows you to focus exclusively on building the code you need to log and moderate your subreddit.

## TODO

- [ ] Expand documentation - The code is fairly well documented, but additional external documentation would be helpful
- [ ] Enable the ability to stream Wiki Pages
- [ ] Simplify passing params to streams
- [ ] A special stream for monitoring a bot's inbox
- [ ] Your idea?

## Contributing

Contributions welcome! Code should generally follow PEP8 guidelines, with several exceptions - that code should be indented with tabs instead of spaces being the most important. 
