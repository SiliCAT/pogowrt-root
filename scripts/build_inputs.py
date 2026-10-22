"""Shared inputs for source compilation and ImageBuilder assembly."""


def package_list(path):
    """Read one package name per line, with comments and blank lines allowed."""
    return list(dict.fromkeys(
        name for line in path.read_text().splitlines()
        if (name := line.partition("#")[0].strip())
    ))


def source_config(project):
    base = project / "configs/packages/base.list"
    selections = "\n".join(f"CONFIG_PACKAGE_{name}=y" for name in package_list(base))
    return (
        (project / "configs/openwrt.config").read_text().rstrip()
        + "\n\n# Generated from configs/packages/base.list\n" + selections
        + "\n\n# Additional packages for ImageBuilder\n"
        + (project / "configs/ib-extra.config").read_text().rstrip() + "\n"
    )


def image_packages(project):
    return list(dict.fromkeys(
        package_list(project / "configs/packages/base.list")
        + package_list(project / "images/luci/packages.list")
    ))
