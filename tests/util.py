from __future__ import annotations

import os
import secrets
import shutil
import stat
import string
from contextlib import contextmanager, suppress
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Tuple

from pydantic.dataclasses import dataclass

from semantic_release.changelog.context import make_changelog_context
from semantic_release.changelog.release_history import ReleaseHistory
from semantic_release.cli.commands import main
from semantic_release.commit_parser._base import CommitParser, ParserOptions
from semantic_release.commit_parser.token import ParseResult

if TYPE_CHECKING:
    import filecmp
    from pathlib import Path
    from typing import Any, Generator, Iterable, TypeVar

    try:
        from typing import TypeAlias
    except ImportError:
        from typing_extensions import TypeAlias

    from unittest.mock import MagicMock

    from git import Repo

    from semantic_release.cli.config import RuntimeContext

    _R = TypeVar("_R")

    GitCommandWrapperType: TypeAlias = main.Repo.GitCommandWrapperType


def copy_dir_tree(src_dir: Path | str, dst_dir: Path | str) -> None:
    """Compatibility wrapper for shutil.copytree"""
    # python3.8+
    shutil.copytree(
        src=str(src_dir),
        dst=str(dst_dir),
        dirs_exist_ok=True,
    )


def remove_dir_tree(directory: Path | str = ".", force: bool = False) -> None:
    """
    Compatibility wrapper for shutil.rmtree

    Helpful for deleting directories with .git/* files, which usually have some
    read-only permissions
    """

    def on_read_only_error(func, path, exc_info):
        os.chmod(path, stat.S_IWRITE)
        os.unlink(path)

    # Prevent error if already deleted or never existed, that is our desired state
    with suppress(FileNotFoundError):
        shutil.rmtree(str(directory), onerror=on_read_only_error if force else None)


@contextmanager
def temporary_working_directory(directory: Path | str) -> Generator[None, None, None]:
    cwd = os.getcwd()
    os.chdir(str(directory))
    try:
        yield
    finally:
        os.chdir(cwd)


def shortuid(length: int = 8) -> str:
    alphabet = string.ascii_lowercase + string.digits

    return "".join(secrets.choice(alphabet) for _ in range(length))


def add_text_to_file(repo: Repo, filename: str, text: str | None = None):
    with open(f"{repo.working_tree_dir}/{filename}", "a+") as f:
        f.write(text or f"default text {shortuid(12)}")
        f.write("\n")

    repo.index.add(filename)


@contextmanager
def netrc_file(machine: str) -> NamedTemporaryFile:
    with NamedTemporaryFile("w") as netrc:
        # Add these attributes to use in tests as source of truth
        netrc.login_username = "username"
        netrc.login_password = "password"

        netrc.write(f"machine {machine}" + "\n")
        netrc.write(f"login {netrc.login_username}" + "\n")
        netrc.write(f"password {netrc.login_password}" + "\n")
        netrc.flush()

        yield netrc


def flatten_dircmp(dcmp: filecmp.dircmp) -> list[str]:
    return dcmp.diff_files + [
        os.sep.join((directory, file))
        for directory, cmp in dcmp.subdirs.items()
        for file in flatten_dircmp(cmp)
    ]


def xdist_sort_hack(it: Iterable[_R]) -> Iterable[_R]:
    """
    hack for pytest-xdist

    https://pytest-xdist.readthedocs.io/en/latest/known-limitations.html#workarounds

    taking an iterable of params for a pytest.mark.parametrize decorator, this
    ensures a deterministic sort so that xdist can always work

    Being able to use `pytest -nauto` is a huge speedup on testing
    """
    return dict(enumerate(it)).values()


def actions_output_to_dict(output: str) -> dict[str, str]:
    return {line.split("=")[0]: line.split("=")[1] for line in output.splitlines()}


def get_release_history_from_context(runtime_context: RuntimeContext) -> ReleaseHistory:
    rh = ReleaseHistory.from_git_history(
        runtime_context.repo,
        runtime_context.version_translator,
        runtime_context.commit_parser,
        runtime_context.changelog_excluded_commit_patterns,
    )
    changelog_context = make_changelog_context(runtime_context.hvcs_client, rh)
    changelog_context.bind_to_environment(runtime_context.template_environment)
    return rh


def prepare_mocked_git_command_wrapper_type(
    **mocked_methods: MagicMock,
) -> type[GitCommandWrapperType]:
    """
    Mock the specified methods of `Repo.GitCommandWrapperType` (`git.Git` by default).

    Initialized `MagicMock` objects are passed as keyword arguments, where the argument
    name is the name of the method to mock.

    For example, the following invocation mocks the `Repo.git.push()` command / method.

    Arrange:
    >>> from unittest.mock import MagicMock
    >>> from git import Repo

    >>> mocked_push = MagicMock()
    >>> cls = prepare_mocked_git_command_wrapper_type(push=mocked_push)
    >>> Repo.GitCommandWrapperType = cls
    >>> repo = Repo(".")

    Act:
    >>> repo.git.push("origin", "master")
    <MagicMock name='mock()' id='...'>

    Assert:
    >>> mocked_push.assert_called_once()
    """

    class MockGitCommandWrapperType(main.Repo.GitCommandWrapperType):
        def __getattr__(self, name: str) -> Any:
            try:
                return object.__getattribute__(self, f"mocked_{name}")
            except AttributeError:
                return super().__getattr__(name)

    for name, method in mocked_methods.items():
        setattr(MockGitCommandWrapperType, f"mocked_{name}", method)
    return MockGitCommandWrapperType


class CustomParserWithNoOpts(CommitParser[ParseResult, ParserOptions]):
    parser_options = ParserOptions


@dataclass
class CustomParserOpts(ParserOptions):
    allowed_tags: Tuple[str, ...] = ("new", "custom")  # noqa: UP006


class CustomParserWithOpts(CommitParser[ParseResult, CustomParserOpts]):
    parser_options = CustomParserOpts
