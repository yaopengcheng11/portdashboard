"""Packaging for cli-anything-portdashboard."""

from setuptools import setup, find_namespace_packages

setup(
    name="cli-anything-portdashboard",
    version="1.0.0",
    description="Agent-native CLI for Port Dashboard — local service and port management",
    author="CLI-Anything Community",
    license="Apache-2.0",
    packages=find_namespace_packages(include=["cli_anything.*"]),
    install_requires=[
        "click>=8.0",
        "requests>=2.28",
    ],
    extras_require={
        "repl": ["prompt_toolkit>=3.0"],
    },
    package_data={
        "cli_anything.portdashboard": ["skills/*.md"],
    },
    entry_points={
        "console_scripts": [
            "cli-anything-portdashboard=cli_anything.portdashboard.portdashboard_cli:cli",
        ],
    },
    python_requires=">=3.10",
)
