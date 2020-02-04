import sys
import shutil
import argparse
import subprocess
import json
import time
import multiprocessing
import os
cores = multiprocessing.cpu_count()
try:
    import orjson as dec_json
except ImportError:
    import json as dec_json
    print("orjson not installed.\nUsing default python may cause slowdowns.")
import asyncio

try:
    import numpy
    import matplotlib.pyplot as matplot
except ImportError:
    sys.stderr.write("Error: Missing package 'python3-matplotlib'\n")
    sys.exit(1)

# check for ffprobe in path
if not shutil.which("ffprobe"):
    sys.stderr.write("Error: Missing ffprobe from package 'ffmpeg'\n")
    sys.exit(1)

format_list = list(
    matplot.figure().canvas.get_supported_filetypes().keys())
matplot.close()  # destroy test figure

parser = argparse.ArgumentParser(
    description="Graph bitrate for audio/video streams")
parser.add_argument('input', help="input file/stream", metavar="INPUT")
parser.add_argument('-s', '--stream', help="stream type",
                    choices=["audio", "video"], default="video")
parser.add_argument('-o', '--output', help="output file")
parser.add_argument('-idx', '--index', help="Set stream index", type=int, default=0)
parser.add_argument('-f', '--format', help="output file format",
                    choices=format_list)
parser.add_argument('-p', '--progress', help="show progress",
                    action='store_true')
parser.add_argument('--min', help="set plot minimum (kbps)", type=int)
parser.add_argument('--max', help="set plot maximum (kbps)", type=int)
args = parser.parse_args()

if args.format and not args.output:
    sys.stderr.write("Error: Output format requires output file\n")
    sys.exit(1)

# check given y-axis limits
if args.min and args.max and (args.min >= args.max):
    sys.stderr.write("Error: Maximum should be greater than minimum\n")
    sys.exit(1)

frame_rate = None
total_time = None

p = subprocess.check_output(
    ["ffprobe",
     "-show_entries", "format",
     "-print_format", "json=compact=1",
     args.input
     ],
    stderr=subprocess.DEVNULL)
fmt_data = json.loads(p.decode("utf-8"))

if args.stream[0].lower() == "v":
    spec = "V"
else:
    spec = "a"

p = subprocess.check_output(
    ["ffprobe",
     "-show_entries", "stream",
     "-select_streams", f"V:{args.index}",
     "-print_format", "json=compact=1",
     args.input
     ],
    stderr=subprocess.DEVNULL)
stream_data = json.loads(p.decode("utf-8"))
if spec == "V":
    (dividend, divisor) = stream_data["streams"][0].get("avg_frame_rate").split("/")
    frame_rate = float(dividend) / float(divisor)
total_time = float(fmt_data["format"].get('duration'))


def main():
    frame_count = 0
    now = time.time()
    bitrate_data = {}
    once = False
    global frame_rate
    with subprocess.Popen(
            ["ffprobe", "-threads", f"{cores-1}",
             "-show_entries", "packet=size,duration_time,pts_time,flags",
             "-select_streams", f"{spec}:{args.index}",
             "-print_format", "json=compact=1",
             args.input
             ], stdout=subprocess.PIPE,
             stderr=subprocess.DEVNULL) as proc_frame:
        for stdout_line in iter(proc_frame.stdout.readline, ""):
            stdout_line = stdout_line.decode("utf-8").replace("\r\n", "").strip()

            if len(stdout_line) == 0:
                break
            if len(stdout_line) > 0 and stdout_line[-1] == ",":
                stdout_line = stdout_line[:-1]
            if "pts_time" in stdout_line:
                try:
                    decoded = dec_json.loads(stdout_line)
                except json.decoder.JSONDecodeError:
                    print(stdout_line)
                    raise Exception
                if not once and spec == "a":
                    frame_rate = 1.0 / float(decoded.get('duration_time'))
                    once = True

                frame_type = decoded.get("flags") if spec == "V" else "A"
                if frame_type == "K_":
                    frame_type = "I"
                else:
                    frame_type = "P"
                frame_bitrate = (float(decoded.get('size')) * 8 / 1000) * frame_rate
                frame_time = float(decoded.get("pts_time"))
                frame = (frame_time, frame_bitrate)
                if frame_type not in bitrate_data:
                    bitrate_data[frame_type] = []
                bitrate_data[frame_type].append(frame)
                frame_count += 1
                if total_time is not None:
                    percent = (frame_time / total_time) * 100.0
                    sys.stdout.write("\rProgress: {:5.2f}%".format(percent))
    print(flush=True)

    print(f"Done gathering data: Taken {time.time() - now:.4f}s")
    print("Drawing matplot...")
    matplot.figure().canvas.set_window_title(args.input)
    matplot.title(f"{os.path.basename(args.input)}")
    matplot.xlabel("Time (sec)")
    matplot.ylabel("Frame Bitrate (kbit/s)")
    matplot.grid(True)
    # map frame type to color
    frame_type_color = {
        # audio
        'A': 'red',
        # video
        'I': 'red',
        'P': 'green',
        'B': 'blue'
    }
    global_peak_bitrate = 0.0
    global_mean_bitrate = 0.0

    for frame_type in ['I', 'P', 'B', 'A']:

        # skip frame type if missing
        if frame_type not in bitrate_data:
            continue

        # convert list of tuples to numpy 2d array
        frame_list = bitrate_data[frame_type]
        frame_array = numpy.array(frame_list)

        # update global peak bitrate
        peak_bitrate = frame_array.max(0)[1]
        if peak_bitrate > global_peak_bitrate:
            global_peak_bitrate = peak_bitrate

        # update global mean bitrate (using piecewise mean)
        mean_bitrate = frame_array.mean(0)[1]
        global_mean_bitrate += mean_bitrate * (len(frame_list) / frame_count)

        # plot chart using gnuplot-like impulses
        matplot.vlines(
            frame_array[:, 0], [0], frame_array[:, 1],
            color=frame_type_color[frame_type],
            label="{} Frames".format(frame_type))

    # set y-axis limits if requested
    if args.min:
        matplot.ylim(ymin=args.min)
    if args.max:
        matplot.ylim(ymax=args.max)

    # calculate peak line position (left 15%, above line)
    peak_text_x = matplot.xlim()[1] * 0.15
    peak_text_y = global_peak_bitrate + \
                  ((matplot.ylim()[1] - matplot.ylim()[0]) * 0.015)
    peak_text = "peak ({:.0f})".format(global_peak_bitrate)

    # draw peak as think black line w/ text
    matplot.axhline(global_peak_bitrate, linewidth=2, color='black')
    matplot.text(peak_text_x, peak_text_y, peak_text,
                 horizontalalignment='center', fontweight='bold', color='black')

    # calculate mean line position (right 85%, above line)
    mean_text_x = matplot.xlim()[1] * 0.85
    mean_text_y = global_mean_bitrate + \
                  ((matplot.ylim()[1] - matplot.ylim()[0]) * 0.015)
    mean_text = "mean ({:.0f})".format(global_mean_bitrate)

    # draw mean as think black line w/ text
    matplot.axhline(global_mean_bitrate, linewidth=2, color='black')
    matplot.text(mean_text_x, mean_text_y, mean_text,
                 horizontalalignment='center', fontweight='bold', color='black')

    matplot.legend()

    # render graph to file (if requested) or screen
    if args.output:
        matplot.savefig(args.output, format=args.format)
    else:
        matplot.show()


if __name__ == '__main__':
    main()