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
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };

        # Wraps chromium with fonts and dbus so it works in containers without system fonts.
        # Without this, chrome logs a lot of errors and hits some fatal errors.
        chromium-headless = let
          fontsConf = pkgs.makeFontsConf { fontDirectories = [ pkgs.dejavu_fonts ]; };
          dbusConf = pkgs.writeText "dbus-dummy-system.conf" ''
            <!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
              "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
            <busconfig>
              <type>custom</type>
              <listen>unix:tmpdir=/tmp</listen>
              <auth>EXTERNAL</auth>
              <policy context="default">
                <allow send_destination="*" eavesdrop="true"/>
                <allow eavesdrop="true"/>
                <allow own="*"/>
              </policy>
            </busconfig>
          '';
        in pkgs.writeShellScriptBin "chromium" ''
          export FONTCONFIG_FILE="${fontsConf}"
          # Start a dummy system bus if none exists
          if [ ! -S /run/dbus/system_bus_socket ]; then
            DBUS_SYSTEM_SOCKET=$(${pkgs.dbus}/bin/dbus-daemon --config-file="${dbusConf}" --print-address --fork 2>/dev/null)
            export DBUS_SYSTEM_BUS_ADDRESS="$DBUS_SYSTEM_SOCKET"
          fi
          exec "${pkgs.dbus}/bin/dbus-run-session" \
            --dbus-daemon="${pkgs.dbus}/bin/dbus-daemon" \
            --config-file="${pkgs.dbus}/share/dbus-1/session.conf" \
            "${pkgs.chromium}/bin/chromium" "$@"
        '';

        # Custom playwright browsers directory that replaces the headless shell
        # with our font-aware chromium wrapper. The stock headless shell binary
        # can't render text because it lacks font configuration.
        playwright-browsers = pkgs.runCommand "playwright-browsers" {} ''
          mkdir -p $out
          for entry in ${pkgs.playwright-driver.browsers}/*; do
            name=$(basename "$entry")
            if [ "$name" = "chromium_headless_shell-1208" ]; then
              mkdir -p "$out/$name/chrome-headless-shell-linux64"
              for f in "$entry/chrome-headless-shell-linux64/"*; do
                ln -s "$f" "$out/$name/chrome-headless-shell-linux64/$(basename "$f")"
              done
              rm "$out/$name/chrome-headless-shell-linux64/chrome-headless-shell"
              ln -s "${chromium-headless}/bin/chromium" \
                "$out/$name/chrome-headless-shell-linux64/chrome-headless-shell"
            else
              ln -s "$entry" "$out/$name"
            fi
          done
        '';

        # Patch dev-browser to run on nixos, keep files in this tree, and
        # configure playwright to use our font-aware chromium.
        dev-browser = let
          dev-browser-unwrapped = pkgs.stdenv.mkDerivation rec {
            pname = "dev-browser-unwrapped";
            version = "0.2.5";

            src = pkgs.fetchurl {
              url = "https://github.com/SawyerHood/dev-browser/releases/download/v${version}/dev-browser-linux-x64";
              hash = "sha256-yeqnC9BNbbNlPgK+9yJySDiNlWRPe+gvVqNWohkVAvk=";
            };

            dontUnpack = true;

            nativeBuildInputs = [ pkgs.autoPatchelfHook ];
            buildInputs = [ pkgs.stdenv.cc.cc.lib ];

            installPhase = ''
              install -Dm755 $src $out/bin/dev-browser
            '';
          };

          # Bootstrap script that runs once per shell to install daemon deps.
          # `dev-browser install` tries to download Chromium via playwright;
          # we shim npm to skip that since we provide Chromium via Nix.
          setupHook = pkgs.writeText "dev-browser-setup-hook" ''
            _dev_browser_setup() {
              export HOME="''${DEV_BROWSER_HOME:-$HOME}"
              export PLAYWRIGHT_BROWSERS_PATH="${playwright-browsers}"

              local _db_dir="$HOME/.dev-browser"
              if [ ! -d "$_db_dir/node_modules" ]; then
                echo "Bootstrapping dev-browser daemon..."
                local _noop=$(mktemp -d)
                ln -s "$(command -v npm)" "$_noop/npm.real"
                cat > "$_noop/npm" <<'SHIM'
#!/bin/sh
for arg in "$@"; do
  [ "$arg" = "playwright" ] && exit 0
done
exec npm.real "$@"
SHIM
                chmod +x "$_noop/npm"
                PATH="$_noop:$PATH" dev-browser install
                rm -rf "$_noop"
                (cd "$_db_dir" && npm install --save-exact \
                  playwright-core@${pkgs.playwright-driver.version} \
                  playwright@${pkgs.playwright-driver.version} \
                  --ignore-scripts >/dev/null 2>&1)
                echo "Done."
              fi
            }
            _dev_browser_setup
            unset -f _dev_browser_setup
          '';
        in pkgs.symlinkJoin {
          name = "dev-browser";
          paths = [
            (pkgs.writeShellScriptBin "dev-browser" ''
              export HOME="''${DEV_BROWSER_HOME:-$HOME}"
              export PLAYWRIGHT_BROWSERS_PATH="${playwright-browsers}"
              exec ${dev-browser-unwrapped}/bin/dev-browser "$@"
            '')
          ];
          passthru = { inherit setupHook; };
        };

        # Wrap agent-browser to set AGENT_BROWSER_EXECUTABLE_PATH
        agent-browser = let
          agent-browser-unwrapped = pkgs.stdenv.mkDerivation rec {
            pname = "agent-browser";
            version = "0.23.4";

            src = pkgs.fetchurl {
              url = "https://registry.npmjs.org/agent-browser/-/agent-browser-${version}.tgz";
              hash = "sha256-uLi7Ksem211kEFQaa00yIDbGM8IN8GyY/HzE6vtji18=";
            };

            nativeBuildInputs = [ pkgs.autoPatchelfHook ];
            buildInputs = [ pkgs.stdenv.cc.cc.lib ];

            unpackPhase = ''
              tar xzf $src
            '';

            installPhase = ''
              mkdir -p $out/bin
              cp package/bin/agent-browser-linux-x64 $out/bin/agent-browser
              chmod +x $out/bin/agent-browser
            '';
          };
        in pkgs.writeShellScriptBin "agent-browser" ''
          export AGENT_BROWSER_EXECUTABLE_PATH="${chromium-headless}/bin/chromium"
          exec ${agent-browser-unwrapped}/bin/agent-browser "$@"
        '';

        # Trick tilt into keeping its files in this tree
        tilt-wrapped = pkgs.writeShellScriptBin "tilt" ''
          export TILT_DEV_DIR="''${TILT_DEV_DIR:-$HOME/.tilt-dev}"
          exec ${pkgs.tilt}/bin/tilt "$@"
        '';

        packagesList = with pkgs; [
          dev-browser
          graphite-cli
          moreutils # ts for timestamped logs in Tilt
          nodejs_20
          sqlite # For inspecting the db
          tilt-wrapped
          uv
          agent-browser
          chromium-headless
        ];
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = packagesList;
          shellHook = ''
            export PATH="$PWD/.venv/bin:$PATH"
            export DEV_BROWSER_HOME="$PWD/.local"
            export TILT_DEV_DIR="$PWD/.local/tilt-dev"
          '';
        };
      }
    );
}
