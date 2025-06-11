from pathlib import Path
import os
import configparser
import importlib.resources

def get_config_path():
	# Look in the directory of the main script
	try:
		main_dir = Path(os.getcwd())
		return main_dir
	except (AttributeError, KeyError):
		pass  # In interactive mode or weird cases, just skip this
	# Fall back to default config bundled with the module
	return None


def get_config():
	config_path = get_config_path()
	user_config = os.path.join(config_path, 'fenix.ini')
	if os.path.exists(user_config):
		return user_config
	else:
		return None

def get_log_path():
	return get_config_path() / "logs"

def load_config():
	config = configparser.ConfigParser()
	config_path = get_config()

	if config_path and os.path.exists(config_path):
		config.read(config_path)
	else:
		try:
			with importlib.resources.open_text('fenix_framework', 'default_fenix.ini') as f:
				config.read_file(f)
		except FileNotFoundError:
			raise FileNotFoundError("No fenix.ini found and no default_fenix.ini bundled.")

	return config