import hashlib
import importlib
import json
import logging
import pathlib
import shutil
import subprocess
import sys
import tarfile
import zipfile
from configparser import ConfigParser
from optparse import Values
from tempfile import mkdtemp

from kink import inject, di
from pip._internal.cli.req_command import RequirementCommand
from pip._internal.models.target_python import TargetPython
from pip._internal.operations.build.build_tracker import get_build_tracker
from pip._internal.req.req_install import check_legacy_setup_py_options
from pip._internal.utils import temp_dir
from pip._internal.utils.temp_dir import TempDirectory


def initalize_pip_options(options):
    """
    Internal function, initialize pip options
    :params options: the options
    """
    options.retries = 3
    options.no_input = True
    options.cache_dir = mkdtemp()
    options.build_dir = mkdtemp()
    options.src_dir = mkdtemp()
    options.download_dir = mkdtemp()
    options.features_enabled = options.deprecated_features_enabled = []
    options.trusted_hosts = ()
    options.keyring_provider = "auto"
    options.cert = options.client_cert = options.find_links = options.format_control = options.proxy = None
    options.timeout = 300
    options.pre = options.prefer_binary = False

    cfg: ConfigParser = di['config']
    options.index_url = cfg.get('plugin', 'library-index')

    # options.extra_index_urls = ["https://pypi.org/simple"]
    options.extra_index_urls = []
    options.no_index = False
    options.constraints = options.editables = options.requirements = []
    options.use_pep517 = None
    options.isolated_mode = True
    options.build_isolation = True
    options.check_build_deps = True
    options.progress_bar = "on"
    options.require_hashes = False
    options.ignore_dependencies = False


class PythonLibDownloader(RequirementCommand):
    """
    Downloading command that invokes pip to download libraries that required by plugin
    """
    def __init__(self):
        super().__init__("shovel-download", "download plugin libraries")

    @inject
    def download(self, name, data_path: pathlib.Path):
        """
        Start downloading
        :params name: library name
        :params data_path: the root path of diamond shovel.
        """
        options = Values()

        # No idea why these values are all must.
        initalize_pip_options(options)

        session = self.get_default_session(options)
        target_python = TargetPython()

        finder = self._build_package_finder(
            options=options,
            session=session,
            target_python=target_python,
            ignore_requires_python=False,
        )

        build_tracker = self.enter_context(get_build_tracker())

        reqs = self.get_requirements([name], options, finder, session)
        check_legacy_setup_py_options(options, reqs)

        build_dir = TempDirectory()

        preparer = self.make_requirement_preparer(
            temp_build_dir=build_dir,
            options=options,
            build_tracker=build_tracker,
            session=session,
            finder=finder,
            use_user_site=False,
            download_dir=options.download_dir,
        )

        resolver = self.make_resolver(
            preparer=preparer,
            finder=finder,
            options=options,
            ignore_requires_python=False,
            use_pep517=False,
            py_version_info=sys.version_info,
        )

        self.trace_basic_info(finder)

        downloaded = {}
        requirement_set = resolver.resolve(reqs, check_supported_wheels=True)
        for req in requirement_set.requirements.values():
            if req.satisfied_by is None:
                preparer.save_linked_requirement(req)
                downloaded[req.name] = {}
                filename = req.link.filename
                downloaded[req.name]["filename"] = filename
                downloaded[req.name]["sha256"] = hashlib.sha256(
                    (pathlib.Path(options.download_dir) / filename).read_bytes()
                ).hexdigest()

        preparer.prepare_linked_requirements_more(requirement_set.requirements.values())

        for name, metadata in downloaded.items():
            dispatch_python_wheel_decompress(pathlib.Path(options.download_dir) / metadata["filename"], data_path / "libraries")

        return downloaded


_check_passed = []

@inject
def fetch_python_library(name, data_path: pathlib.Path):
    """
    Find a library base on the name, will download one if not found
    :params name: library name
    :params data_path: root of diamond shovel workdir
    """
    try:
        library_dir = data_path / "libraries"
        library_dir.mkdir(exist_ok=True)

        library_index_file = library_dir / "index"
        if not library_index_file.exists():
            library_index_file.write_text("{}")
        library_index = json.loads(library_index_file.read_text())
        if name in library_index:
            return

        downloader = PythonLibDownloader()
        with downloader.main_context():
            with temp_dir.global_tempdir_manager():
                with temp_dir.tempdir_registry():
                    logging.info(f"Downloading dependency {name}")
                    downloaded = downloader.download(name)
        library_index.update(downloaded)
        library_index_file.write_text(json.dumps(library_index))
    finally:
        refresh_python_libraries()


@inject
def refresh_python_libraries(data_path: pathlib.Path):
    """
    Refreshes import caches of libraries
    :params data_path: root of diamond shovel workdir
    """
    library_dir = data_path / "libraries"
    library_dir.mkdir(exist_ok=True)
    sys.path.append(str(library_dir))
    importlib.invalidate_caches()


def dispatch_python_wheel_decompress(file: pathlib.Path, target: pathlib.Path):
    """
    Dispatches decompression of a file, should be a python wheel
    :params file: file to decompress
    :params target: target folder to decompress to
    """
    suffix = ''.join(file.suffixes)
    if suffix.endswith(".zip") or suffix.endswith(".whl"):
        with zipfile.ZipFile(file) as z:
            z.extractall(target)
        return True
    elif suffix.endswith(".tar.gz"):
        with tarfile.open(file) as t:
            t.extractall(target)
        # there might be nested things, we need to deal with them
        sub_folder = target / file.name.replace('.tar.gz', '')
        if sub_folder.exists():
            for f in sub_folder.iterdir():
                f.rename(target / f.name)
            shutil.rmtree(sub_folder)
        return True
    else:
        logging.error(f"Unknown file type {file.suffix}")
        return False


def check_os_libraries(name: str):
    """
    Checks libraries that provided by OS
    :params name: library name
    :returns: a tuple of boolean and a message, True is passed
    """
    os_id = fetch_os_id()

    check_cmd = None
    suggest_install_cmd = None
    if os_id == "debian" or os_id == "ubuntu":
        check_cmd = ["dpkg", "-s", name]
        suggest_install_cmd = f"sudo apt install -y {name}"
    elif os_id == "centos" or os_id == "fedora":
        check_cmd = ["rpm", "-q", name]
        suggest_install_cmd = f"sudo yum install -y {name}"
    elif os_id == "arch":
        check_cmd = ["pacman", "-Q", name]
        suggest_install_cmd = f"sudo pacman -S {name}"

    if check_cmd is None:
        raise ValueError(f"Unsupported OS: {os_id}")

    check_proc = subprocess.run(check_cmd)
    if check_proc.returncode != 0:
        return False, f"Please install one by running: {suggest_install_cmd}"
    return True, "It's OK >w<"

def fetch_os_id():
    """
    Reads OS id, only works on Linux
    :returns: name of current OS
    """
    os_property_file = pathlib.Path("/etc/os-release")
    if not os_property_file.exists():
        os_property_file = pathlib.Path("/usr/lib/os-release")
    if not os_property_file.exists():
        raise ValueError("Unknown OS")
    with os_property_file.open("r") as f:
        for line in f:
            if line.startswith("ID="):
                return line.split("=")[1].strip()
    raise ValueError("Unknown OS")

