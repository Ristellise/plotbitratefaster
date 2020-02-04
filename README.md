# plotbitrate
A faster version of zeroepoch's plotbitrate

### How?

It does the following Optimisations:
  - Use more threads!
  - `frames` requires decoding, so use `packet` instead. [Thanks to doop for this one.]  

The process is more or less now I/O Bound.  
Usage is the same as the original plotbitrate.py.  
However, progress is included by default and there is no way to disable it as of now.
