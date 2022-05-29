import click
from deck.player import (
    pause,
    play,
    queue,
    show_previous,
    show_queue,
    spin,
)


@click.group()
def cli():
    pass

cli.add_command(pause)
cli.add_command(play)
cli.add_command(queue)
cli.add_command(show_previous)
cli.add_command(show_queue)
cli.add_command(spin)


if __name__ == '__main__':
    cli()
