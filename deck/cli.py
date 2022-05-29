import click
from deck.player import play, spin, queue, show_queue, show_previous


@click.group()
def cli():
    pass

cli.add_command(play)
cli.add_command(spin)
cli.add_command(queue)
cli.add_command(show_queue)
cli.add_command(show_previous)


if __name__ == '__main__':
    cli()
