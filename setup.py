from setuptools import setup

setup(
    name='deck',
    version='0.0.1',
    py_modules=['deck'],
    install_requires=[
        'Click',
        'tinytag',
    ],
    entry_points={
        'console_scripts': [
            'deck = deck.cli:cli',
        ],
    },
)
