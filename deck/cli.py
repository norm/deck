import click
from deck.player import (
    next_track,
    pause,
    play,
    previous_track,
    queue,
    show_previous,
    show_queue,
    spin,
)


@click.group()
def cli():
    pass

cli.add_command(pause)
cli.add_command(next_track, name='next')
cli.add_command(play)
cli.add_command(previous_track, name='previous')
cli.add_command(queue)
cli.add_command(show_previous)
cli.add_command(show_queue)
cli.add_command(spin)


if __name__ == '__main__':
    cli()
