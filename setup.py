import setuptools.command.test

with open("README.md", "r", encoding="utf8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="diamond-shovel",
    version="0.0.1",
    author="Diamond Shovel Development Team",
    author_email="diamondshovel@cyberspike.top",
    description="A tool for asset scanning and vulnerability discovery",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://www.cyberspike.top/tools/diamond_shovel",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
    entry_points={
        'console_scripts': [
            'diamond-shovel = diamond_shovel.main:main',
        ],
    },
    install_requires=[
        "kink",
        "flask",
        "requests",
        "geopy"
    ],
    tests_require=[
        "pytest",
        "pytest-cov",
    ]
)
