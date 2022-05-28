import click
from deck.player import play, spin


@click.group()
def cli():
    pass

cli.add_command(play)
cli.add_command(spin)


if __name__ == '__main__':
    cli()
