
{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  buildInputs = [
    pkgs.python3
    pkgs.python3Packages.python-dotenv
    pkgs.python3Packages.python-telegram-bot
  ];
}
