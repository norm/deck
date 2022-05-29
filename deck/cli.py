import click
from deck.player import play, spin, queue


@click.group()
def cli():
    pass

cli.add_command(play)
cli.add_command(spin)
cli.add_command(queue)


if __name__ == '__main__':
    cli()
