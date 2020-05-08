import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="otter_plotter",
    use_scm_version=True,
    setup_requires=["setuptools_scm"],
    author="James Ball",
    author_email="",
    description="Plot live data",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/jmball/otter_plotter",
    py_modules=["plotter"],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GPL-3.0",
        "Operating System :: OS Independent",
    ],
)
