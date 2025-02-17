#!/bin/bash

NAME=$1
PREHOOK=$2
HIDE_GITLOG=$3

CWD=$(pwd)

echo "Setting up environment" >&2

cat > /etc/apt/sources.list.d/debian.sources <<EOF
Types: deb
URIs: http://mirrors.tuna.tsinghua.edu.cn/debian
Suites: bookworm bookworm-updates bookworm-backports
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://mirrors.tuna.tsinghua.edu.cn/debian-security
Suites: bookworm-security
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

EOF

apt-get update
apt-get install -y  build-essential debhelper devscripts dh-sequence-python3 python3-setuptools python3-all git python3-venv python3-pip

echo "Running pre-hook" >&2
if [[ -n $PREHOOK ]]; then
  /bin/bash $PREHOOK || exit 1
fi

mkdir debian

print_changelog()
{
  current_tag=$1
  previous_tag=$(git describe --tags --abbrev=0 $current_tag^)

  tag_message=""
  if [ -z $previous_tag ]; then
    tag_message=$(git log --reverse --format="  * %H %s")
  else
    tag_message=$(git log $previous_tag...$current_tag --format="  * %H %s")
  fi

  urgency="low"
  if [[ ${tag_message,,} = *"security"* ]] || [[ ${tag_message,,} = *"vulnerabilit"* ]]; then
    urgency="high"
  elif [[ ${tag_message,,} = *"fix"* ]]; then
    urgency="medium"
  fi

  if [[ -n $HIDE_GITLOG ]]; then
    msg_pool=("Discovered a diamond ore" "Had a nice sleep with sheep" "Tried to swim in lava" "Blew up by a creeper" "Removed herobrine" "Crafted an exploit" "Fuzzed with bees" "Swamped in slimes" "Got 1 miss" "Farmed 727 pp")
    tag_message="  * ${msg_pool[$((16#$(git rev-parse --short HEAD))) % ${#msg_pool[@]}]}"
  fi

  tag_commiter=$(git log -1 --format="%an <%ae>  %aD" $current_tag --)

  echo -e "${NAME} (${current_tag}) UNRELEASED; urgency=${urgency}\n" # We do not want them get uploaded to debian
  echo -e "${tag_message}\n"
  echo -e " -- ${tag_commiter}\n"

  if [[ -n $previous_tag ]]; then
    print_changelog $previous_tag
  fi
}

VERSION=$(git describe --tags --abbrev=0)
echo "Generating changelog of version: "$VERSION >&2
print_changelog $VERSION > debian/changelog

echo "Removing unnecessary files" >&2
rm -rf .git building .gitlab-ci.yml .gitmodules Dockerfile ./*.Dockerfile docker-compose.yml
find . -name "__pycache__" -exec rm -rf {} \;
find . -name "*.png" -exec rm -rf {} \;
find . -name "*.xls*" -exec rm -rf {} \;

echo "Fetching dependencies" >&2
mkdir /tmp/archive
pip install --target=$CWD -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple 2>&1 || exit 1
cp -r ./* /tmp/archive/

echo "Creating original package" >&2
pushd /tmp/archive
rm -rf debian
tar -zcf /tmp/${NAME}_${VERSION}.orig.tar.gz ./* > /dev/null 2>&1
popd

echo "Generating debian metadata" >&2
cat >> debian/control <<EOF
Source: ${NAME}
Section: misc
Priority: optional
Maintainer: stupidfish <stupidfish@cyberspike.top>
Rules-Requires-Root: binary-targets
Build-Depends:
 debhelper-compat (= 13),
 dh-sequence-python3,
 python3-setuptools,
 python3-all,
Standards-Version: 4.6.2
Homepage: https://www.cyberspike.top/tools/diamond-shovel

Package: ${NAME}
Architecture: all
Depends:
 \${python3:Depends},
 \${misc:Depends},
 libxext6,
 libcairo2,
 libopenjp2-7,
 libxml2,
 libxslt1.1,
 liblcms2-2,
 libsnappy1v5,
 libc6,
 libdbus-1-3,
 libgtk-3-0,
 libatspi2.0-0,
 libnspr4,
 libxcomposite1,
 libnss3,
 libxfixes3,
 libzstd1,
 libminizip1,
 libc++abi1-16,
 libdouble-conversion3,
 libunwind-16,
 libxdamage1,
 libc++1-16,
 libopus0,
 libx11-6,
 libharfbuzz-subset0,
 libcups2,
 libxkbcommon0,
 libopenh264-7,
 libflac12,
 libatomic1,
 libgcc-s1,
 libexpat1,
 libdrm2,
 libxcb1,
 libatk1.0-0,
 libdav1d6,
 libstdc++6,
 libasound2,
 libpng16-16,
 libevent-2.1-7,
 libpulse0,
 libxrandr2,
 libjpeg62-turbo,
 libfontconfig1,
 libgdm1,
 libpango-1.0-0,
 libwoff1,
 libxnvctrl0,
 libfreetype6,
 zlib1g,
 xdg-utils,
 libatk-bridge2.0-0,
 libglib2.0-0,
 x11-utils,
 libharfbuzz0b,
 libjsoncpp25,
Description: A tool for website vulnerability scanner on companies
 An advanced tool for automated scanning on all website of a Chinese
 company.
EOF

cat >> debian/copyright <<EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Source: https://www.cyberspike.top/tools/diamond-shovel
Upstream-Name: diamond-shovel
Upstream-Contact: stupidfish <stupidfish@cyberspike.top>

Files:
 *
Copyright:
 2024 stupidfish
 2024 astro angelfish
License: All Right Reserved
EOF

cat >> debian/postinst <<EOF
#!/bin/sh
set -e
case "\$1" in
    configure)
    ;;

    abort-upgrade|abort-remove|abort-deconfigure)
    ;;

    *)
        diamond-shovel -I -r /
    ;;
esac

#DEBHELPER#

exit 0
EOF

cat >> debian/prerm <<EOF
#!/bin/sh
set -e
case "\$1" in
    remove|upgrade|deconfigure)
    ;;

    failed-upgrade)
    ;;

    *)
    diamond-shovel -u -r /
    ;;
esac

#DEBHELPER#

exit 0
EOF

echo "#!/usr/bin/make -f" > debian/rules
echo "export PYBUILD_NAME=${NAME}" >> debian/rules
echo "%:" >> debian/rules
echo -e "\tdh \$@ --buildsystem=pybuild" >> debian/rules
chmod a+x debian/rules

mkdir -p debian/source
echo "3.0 (native)" > debian/source/format
echo extend-diff-ignore = "^[^/]*[.]egg-info/" > debian/source/options
cp -r . /tmp/${NAME}-${VERSION}
pushd /tmp/${NAME}-${VERSION}

echo "Building package" >&2
DEB_BUILD_OPTIONS=nocheck debuild -us -uc || exit 1

echo "Moving package to output directory" >&2
pushd /tmp/
if [ -z $NO_CLEANUP ]; then
  rm -rf $CWD/dist/*
fi

mkdir -p $CWD/dist

cp *.deb $CWD/dist

if [ -z $NO_CLEANUP ]; then
  rm -rf /tmp/*
fi
popd
