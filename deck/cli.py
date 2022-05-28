import click
from deck.player import play


@click.group()
def cli():
    pass

cli.add_command(play)


if __name__ == '__main__':
    cli()
