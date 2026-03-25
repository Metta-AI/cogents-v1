{
  description = "Health data analysis environment";

  inputs = {
    nixpkgs.url = "nixpkgs/nixos-unstable";
    utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      utils,
    }:
    utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };

        packagesList = [
          pkgs.graphite_cli
          pkgs.nodejs_20
          pkgs.sqlite # For inspecting the db
          pkgs.uv
        ];
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = packagesList;
          shellHook = ''
            export PATH="$PWD/.venv/bin:$PATH"
          '';
        };
      }
    );
}
