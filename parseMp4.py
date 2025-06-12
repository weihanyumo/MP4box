import re
import struct
import tkinter as tk
from tkinter import ttk
from tkinter import filedialog
import io
import sys
import time
from tkinter import simpledialog
import uuid
import time
import math
from enum import Enum, auto, unique
from dataclasses import dataclass
from typing import Optional
import requests
import numpy as np

import cv2
from PIL import Image, ImageTk
from urllib.parse import urlparse



class NetStream:
    def __init__(self, url):
        self.url = url
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        self.size = self.get_size()
        self.position = 0
        self.buffer = b''
        self.chunk_size = 8192 * 4  # 增加块大小
        
    def get_size(self):
        try:
            resp = self.session.head(self.url, allow_redirects=True)
            resp.raise_for_status()
            if 'Content-Length' in resp.headers:
                len = int(resp.headers['Content-Length'])
                print(f"文件大小: {len} bytes")
                return len
            
        except Exception as e:
            print(f"HEAD请求失败: {e}")
        
        try:
            headers = {'Range': 'bytes=0-255'}
            resp = self.session.get(self.url, headers=headers, allow_redirects=True)
            resp.raise_for_status()
            
            # 从Content-Range获取完整大小
            if 'Content-Range' in resp.headers:
                content_range = resp.headers['Content-Range']
                match = re.search(r'/(\d+)$', content_range)
                if match:
                    return int(match.group(1))
            
            # 如果Content-Range不存在，但Content-Length存在
            if 'Content-Length' in resp.headers:
                return int(resp.headers['Content-Length'])
            
            # 作为最后手段，尝试获取整个文件大小
            resp = self.session.get(self.url, stream=True)
            resp.raise_for_status()
            return int(resp.headers.get('Content-Length', 0))
        except Exception as e:
            print(f"获取文件大小失败: {e}")
            raise RuntimeError(f"无法获取文件大小: {e}")
    
    def read(self, size=None):
        if size is None:
            size = self.size - self.position
            
        print(f"读取数据: 位置 {self.position}, 大小 {size} bytes")
        data = b''
        while len(data) < size:
            if not self.buffer:
                start = self.position
                end = min(self.size, start + self.chunk_size)
                headers = {'Range': f'bytes={start}-{end-1}'}
                try:
                    resp = self.session.get(self.url, headers=headers, stream=True)
                    resp.raise_for_status()
                    self.buffer = resp.content
                except Exception as e:
                    print(f"读取数据失败: {e}")
                    # 尝试重新连接
                    time.sleep(0.5)
                    continue
            
            take = min(size - len(data), len(self.buffer))
            data += self.buffer[:take]
            self.buffer = self.buffer[take:]
            self.position += take
            
        return data
    
    def seek(self, offset, whence=io.SEEK_SET):
        print(f"Seek: 位置 {self.position}, 偏移 {offset}, whence {whence}")
        if whence == io.SEEK_SET:
            self.position = offset
        elif whence == io.SEEK_CUR:
            self.position += offset
        elif whence == io.SEEK_END:
            self.position = self.size + offset
        self.position = max(0, min(self.position, self.size))
        self.buffer = b''  # 清空缓冲区
        return self.position


class TrackType(Enum):
    Unkonw = 0
    Video = 1
    Audio = 2
    Other = 3
    
class BitReader:
    def __init__(self, data):
        self.data = data
        self.ptr = 0
        self.bit_pos = 0
    
    def read_bit(self):
        if self.ptr >= len(self.data):
            return 0

        bit = (self.data[self.ptr] >> (7 - self.bit_pos)) & 1
        self.bit_pos += 1
        if self.bit_pos >= 8:
            self.bit_pos = 0
            self.ptr += 1
        return bit
    
    def read_bits(self, n):
        val = 0
        for _ in range(n):
            val = (val << 1) | self.read_bit()
        return val
    
    def read_ue(self):
        leading_zeros = 0
        while self.read_bit() == 0:
            leading_zeros += 1
        if leading_zeros == 0:
            return 0
        return (1 << leading_zeros) - 1 + self.read_bits(leading_zeros)
    
    def read_se(self):
        ue = self.read_ue()
        return (ue + 1) // 2 if (ue % 2) else -(ue // 2)



@dataclass
class FrameInfo:
    index: int
    pts: float
    dts: float
    duration: float
    offset: int
    size: int
    flags:str
    data: Optional[bytes] = None
    
    def __init__(self):
        index = 0
    
        
class TRACK:
    def __init__(self):
        self.timescale = 0
        self.handler_type = 'unkown'
        self.codec_type = "unkown"
        
        self.elst = []
        self.stts = []
        self.ctts = []
        self.stsz = []
        self.stsc = []
        self.stco = []
        self.stss = []
        self.frame_start_positions =[]
        self.cumulativeTime=0
        self.duration = 0
        self.trackID = 0
        
    def calculate_frame_info(self, file_path):
        dts = 0
        dts_list = []
        pts_list = []
        offsets = []
        sizes = []
        chunk_index = 0
        sample_index = 0

        for sample_count, sample_delta in self.stts:
            for _ in range(sample_count):
                dts_list.append(dts/self.timescale)
                dts += sample_delta

        index=0
        if self.ctts and len(self.ctts) > 0:
            for sample_count, offset in self.ctts:
                count = 0
                while count < sample_count:
                    pts_list.append(dts_list[index] + offset/self.timescale)
                    index += 1
                    count+=1
        else:
            pts_list = dts_list[:]

        offsets = []
        chunk_index = 0
        sample_index = 0
        for i, (first_chunk, samples_per_chunk, _) in enumerate(self.stsc):
            next_first_chunk = self.stsc[i + 1][0] if i + 1 < len(self.stsc) else len(self.stco) + 1
            while chunk_index + 1 < next_first_chunk:
                chunk_offset = self.stco[chunk_index]
                for _ in range(samples_per_chunk):
                    offsets.append(chunk_offset)
                    chunk_offset += self.stsz[sample_index]
                    sizes.append(self.stsz[sample_index])
                    sample_index += 1
                chunk_index += 1
        self.frame_start_positions = offsets[:]
        frames = []
        with open(file_path, 'rb') as file:
            for i in range(len(self.stsz)):
                flags = self.handler_type
                if self.handler_type == 'vide':
                    if self.codec_type == "hvcc":
                        flags="B-Frame"
                        if i+1 in self.stss:
                            flag="I-Frame"
                    elif self.codec_type == "avcc":
                        flags=self.getFrameType(file, offsets[i])
                    
               
                frame = FrameInfo()
                frame.dts = dts_list[i]
                frame.pts = pts_list[i]
                frame.size = sizes[i]
                frame.offset = offsets[i]
                frame.flags = flags
                frames.append(frame)
                
            frames_sorted = sorted(frames, key=lambda f: f.pts)
            return frames_sorted

    def getFrameType(self, file, offset):
        pos = 0
        while True:
            file.seek(offset+pos)
            box_data = file.read(8)
            len,data = struct.unpack(">I4s", box_data[0:8])
            nal_type = data[0] & 0x1F
            
            if nal_type ==5:
                return "IDR"
            elif nal_type == 1:
                reader = BitReader(data[1:])
                offset = reader.read_ue()
                slice_type = reader.read_ue()
                if slice_type in [0, 3, 5, 8]:
                    return "P"
                elif slice_type in [1, 6]:
                    return "B"
                else:
                    return "I"
            else:
                pos += len+4

#MP4ParserApp
class MP4ParserApp:
    
    def __init__(self, root, source):
        self.root = root
        self.root.title("MP4 Box Parser")

        self.source = source
        self.is_network_stream = False
        self.stream = None
        self.frame_start_positions = []
        self.total_frames = 0 
        self.box_descriptions = {}  
        self.box_hex_data = {}  
        self.timescale = 1
        self.duration = 0
        self.tracks = []
        self.currentTrak = None
        self.moof_startPos =0
        self.stss = []
        self.mdat_item_id = -1
        self.totlalFrameCount = 0;
        self.frame_info_list = []
        self.truns = {}
        self.trunItems=[]
        self.selected_item = None
        
        # 检查是否是网络流
        parsed_url = urlparse(source)
        if parsed_url.scheme in ('http', 'https'):
            self.is_network_stream = True
            try:
                # 使用流式请求
                self.stream = requests.get(source, stream=True)
                self.stream.raise_for_status()
            except requests.RequestException as e:
                tk.messagebox.showerror("错误", f"无法获取网络流: {e}")
                return
        
        # main frame
        self.main_frame = tk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.file_label = tk.Label(self.main_frame, text=source, font=("Arial", 12, "bold"))
        self.file_label.pack(anchor="w")
        
        vertical_pane = tk.PanedWindow(self.main_frame, orient=tk.VERTICAL)
        vertical_pane.pack(fill=tk.BOTH, expand=True)
        # 左侧 Treeview 组件
        tree_frame = tk.Frame(vertical_pane)
        tree_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(tree_frame, columns=("Type",  "Start Address", "Size"))
        self.tree.heading("#0", text="Box Name", anchor="w")
        self.tree.heading("Type", text="Type", anchor="w")
        self.tree.heading("Size", text="Size (bytes)", anchor="w")
        self.tree.heading("Start Address", text="Start Address", anchor="w")
       # self.tree.heading("Description", text="description", anchor="w")

        self.tree.column("#0", width=200)
        self.tree.column("Type", width=100)
        self.tree.column("Size", width=100)
        self.tree.column("Start Address", width=150)        
        #self.tree.column("Description", width=300)

        self.tree.pack(fill=tk.BOTH, expand=True)

        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        vertical_pane.add(tree_frame)
        
        bottom_pane = tk.PanedWindow(vertical_pane, orient=tk.HORIZONTAL)
        bottom_pane.pack(fill=tk.BOTH, expand=True)

        box_description_frame = tk.Frame(bottom_pane)
        self.description_label = tk.Label(box_description_frame, text="Box Description:", font=("Arial", 12, "bold"))
        self.description_label.pack(anchor="w")

        desc_scroll_y = tk.Scrollbar(box_description_frame, orient=tk.VERTICAL)
        self.frame_listbox = tk.Listbox(box_description_frame, height=10, font=("Arial", 10))
        self.frame_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        desc_scroll_y.config(command=self.frame_listbox.yview)
        self.frame_listbox.config(yscrollcommand=desc_scroll_y.set)
        desc_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

        bottom_pane.add(box_description_frame, minsize=100, width=500)

        hex_frame = tk.Frame(bottom_pane)
        self.hex_label = tk.Label(hex_frame, text="Hex Data:", font=("Arial", 12, "bold"))
        self.hex_label.pack(anchor="w")

        hex_data_frame = tk.Frame(hex_frame)
        hex_data_frame.pack(fill=tk.BOTH, expand=True)

        hex_scroll_x = tk.Scrollbar(hex_data_frame, orient=tk.HORIZONTAL)
        hex_scroll_y = tk.Scrollbar(hex_data_frame, orient=tk.VERTICAL)

        self.hex_text = tk.Text(
            hex_data_frame, height=10, wrap="none", font=("Courier", 10),
            yscrollcommand=hex_scroll_y.set, xscrollcommand=hex_scroll_x.set
        )

        self.hex_text.bind("<<Selection>>", self.on_hex_selection)
        
        hex_scroll_x.config(command=self.hex_text.xview)
        hex_scroll_y.config(command=self.hex_text.yview)

        self.hex_text.grid(row=0, column=0, sticky="nsew")
        hex_scroll_y.grid(row=0, column=1, sticky="ns")
        hex_scroll_x.grid(row=1, column=0, sticky="ew")

        hex_data_frame.grid_rowconfigure(0, weight=1)
        hex_data_frame.grid_columnconfigure(0, weight=1)

        bottom_pane.add(hex_frame, minsize=100, width=500)
        vertical_pane.add(bottom_pane)

        if self.is_network_stream:
            # 对于网络流，创建一个临时文件来存储数据
            import tempfile
            self.temp_file = tempfile.NamedTemporaryFile(delete=False)
            for chunk in self.stream.iter_content(chunk_size=8192):
                if chunk:
                    self.temp_file.write(chunk)
            self.temp_file.close()
            self.parse_fmp4(self.temp_file.name)
        else:
            self.parse_fmp4(source)

    def remove_trees(self):
        self.trunItems.clear
        self.frame_listbox.delete(0, tk.END)
        self.main_frame.pack_forget()
        self.root.update_idletasks()
    
    def show_frame_list(self,frame_info_list ):
        if not self.tracks:
            return

        self.frame_listbox.delete(0, tk.END)
        if len(frame_info_list) >= 1:
            for track_index, idx,frame in frame_info_list:
                display_text = f"Track {track_index + 1}  Frame {idx + 1}  PTS: {frame.pts:.3f} offset: {frame.offset} size:{frame.size} Flags: {frame.flags}"
                self.frame_listbox.insert(tk.END, display_text)           

        self.frame_listbox.bind("<<ListboxSelect>>", self.on_frame_selected)
        
    def isItemTrun(self, item_id):
        #print(f"self.trunItems count:{self.trunItems} item_id:{item_id}\n")
        return item_id in self.trunItems
    
    def on_tree_select(self, event):
        selected_item = self.tree.selection()
        self.selected_item = None
        if selected_item:
            self.selected_item = selected_item[0];
            if selected_item[0] == self.mdat_item_id:
                self.selected_mada = True
                if len(self.frame_info_list) < 1:
                    for track_index, track in enumerate(self.tracks):
                        frames = track.calculate_frame_info(self.source)
                        for idx, frame in enumerate(frames):
                            self.frame_info_list.append((track_index, idx, frame))
        
                self.show_frame_list(self.frame_info_list)
            elif self.isItemTrun(selected_item[0]):
                self.frame_info_list = self.truns[selected_item[0]]
                self.frame_listbox.delete(0, tk.END)
                if len(self.frame_info_list) >= 1:
                    for frame in self.frame_info_list:
                        display_text = f" PTS: {frame.pts:.3f} offset: {frame.offset} size:{frame.size} Flags: {frame.flags:02x}"
                        self.frame_listbox.insert(tk.END, display_text)           

                self.frame_listbox.bind("<<ListboxSelect>>", self.on_frame_selected)
            else:
                description = self.box_descriptions.get(selected_item[0], "No description available")
                self.frame_listbox.delete(0, tk.END)  # 清除旧内容
                lines = description.splitlines()  # 按 \n 分行
                for line in lines:
                    self.frame_listbox.insert(tk.END, line)
            hex_data = self.box_hex_data.get(selected_item[0], "No hex data available")
            self.hex_text.delete("1.0", tk.END)
            self.hex_text.insert(tk.END, hex_data)

    def on_frame_selected(self, event):
        selected = self.frame_listbox.curselection()
        if not selected:
            print("no seletctd\n")
            return
        # print(f"selected:{selected} self.selectd_item:{self.selected_item} self.mdat_item_id:{self.mdat_item_id}\n")
        data=None
        if self.selected_item == self.mdat_item_id:
            index = selected[0]
            if index < len(self.frame_info_list):
                track_index, frame_index, frame = self.frame_info_list[index]
                with open(self.temp_file.name if self.is_network_stream else self.source, 'rb') as file:
                    file.seek(frame.offset)
                    data = file.read(frame.size)
                    self.hex_text.delete("1.0", tk.END)
                    self.hex_text.insert(tk.END, self.get_hex_data(data, "frame"))
        elif self.isItemTrun(self.selected_item):
            index = selected[0]
            # print(f"selected index:{index}\n")
            if index < len(self.frame_info_list):
                frame = self.frame_info_list[index]
                with open(self.temp_file.name if self.is_network_stream else self.source, 'rb') as file:
                    file.seek(frame.offset)
                    data = file.read(frame.size)
                    self.hex_text.delete("1.0", tk.END)
                    self.hex_text.insert(tk.END, self.get_hex_data(data, "frame"))

        if data is None:
            print("no data\n")
        else:
            if frame.flags.startswith("I") or frame.flags.startswith("P") or frame.flags.startswith("B"):
                self.show_frame_image(data, f"Track {track_index + 1} - Frame {frame_index + 1}")
                
    def show_frame_image(self, data, title="帧图像"):
        try:
            np_arr = np.frombuffer(data, dtype=np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError("无法解码帧数据")

            # 转换为 RGB 并用 Pillow 展示
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(img_rgb)
            img_tk = ImageTk.PhotoImage(pil_img)

            # 弹出窗口
            top = tk.Toplevel()
            top.title(title)
            label = tk.Label(top, image=img_tk)
            label.image = img_tk  # 防止被 GC
            label.pack()
        except Exception as e:
            tk.messagebox.showerror("错误", f"无法解码帧图像: {e}")
            
    def on_hex_selection(self, event):
        try:
            selection = self.hex_text.get(tk.SEL_FIRST, tk.SEL_LAST).strip()
        except tk.TclError:
            return
        try:
            hex_str = selection.replace(" ", "").replace("\n", "")
            if len(hex_str) % 2 != 0:
                return 

            byte_values = [int(hex_str[i:i+2], 16) for i in range(0, len(hex_str), 2)]
            int_value = int.from_bytes(byte_values, byteorder='big') 
            self.hex_label.config(text=f"Hex Data: Decimal {int_value}")

        except Exception as e:
            print("Invalid selection:", e)

    def parse_fmp4(self, file_path):
        with open(file_path, 'rb') as file:
            offset = 0
            while True:
                box_size, box_type, box_data, box_header = self.read_box(file)
                if not box_size:
                    break  
                hex_data = self.get_hex_data(box_header + box_data, box_type) 
                self.add_box_to_treeview(box_type, box_size, box_data, offset, hex_data)
                offset += box_size  

    def read_box(self, file):
        box_header = file.read(8)
        if len(box_header) < 8:
            #print("read return null")
            return None, None, None, None
        box_size, box_type = struct.unpack('>I4s', box_header)
        box_type = box_type.decode('utf-8', errors='ignore')

        box_data = file.read(box_size - 8) if box_size > 8 else b''
        #print(f"type:{box_type} size: {box_size} data_len: {len(box_data)}")
        return box_size, box_type, box_data, box_header

    def read_size(self, file, size):
        return file.read(size)

    def get_hex_data(self, box_data, box_type):
        lines = []
        if box_type == "mdat":
            return lines
        for i in range(0, len(box_data), 16):
            chunk = box_data[i:i+16]
            chunk1 = box_data[i:i+8]
            chunk2 = box_data[i+8:i+16]
            
            hex_part = ' '.join(f"{byte:02X}" for byte in chunk1)
            hex_part += "  "
            hex_part += ' '.join(f"{byte:02X}" for byte in chunk2)
            
            ascii_part = ''.join(chr(byte) if 32 <= byte <= 126 else '.' for byte in chunk1)
            ascii_part += ''.join(chr(byte) if 32 <= byte <= 126 else '.' for byte in chunk2)
            lines.append(f"{hex_part:<48}  {ascii_part}")
        return '\n'.join(lines)

    def to_hex(self, box_data):
        hex_part = ' '.join(f"{byte:02X}" for byte in box_data)
        return hex_part

    def add_box_to_treeview(self, box_type, box_size, box_data, offset, hex_data, parent_id=""):
        start_address = f"{offset:d}"
        item_id = self.tree.insert(parent_id, "end", text=f"{box_type} Box", values=(box_type, start_address, box_size))
        description = self.get_box_description(offset, box_size, box_type, box_data, item_id)
        if box_type in ['moov', 'trak', 'mdia', 'minf', 'stbl', 'udta', 'edts', 'moof', 'traf','dinf', 'meta','mvex', 'sinf', 'stsd', 'schi']:
            nested_offset = offset + 8  
            if box_type == 'moof':
                self.moof_startPos = offset
            if box_type == 'meta':
                nested_offset = offset + 12
                box_data = box_data[4:]
            if box_type == 'stsd':
                self.parse_stsd_box(box_type, box_size, box_data, offset, description, hex_data, item_id)
                return 
                
            self.read_nested_boxes(io.BytesIO(box_data), nested_offset, item_id)
        self.box_descriptions[item_id] = description  

        self.box_hex_data[item_id] = hex_data 
        if box_type == 'mdat':
            self.mdat_item_id = item_id;

    def read_nested_boxes(self, box_file, offset, parent_id):
        while True:
            box_size, box_type, box_data, box_header = self.read_box(box_file)
            if not box_size:
                break
            else:
                hex_data = self.get_hex_data(box_header+box_data, box_type)
                self.add_box_to_treeview(box_type, box_size, box_data, offset, hex_data, parent_id)
                offset += box_size
 
    def display_frame_info(self):
        total_frames = len(self.frame_start_positions)
        frame_positions = "\n".join([f"帧 {i + 1}: 起始位置 - {start}" for i, start in enumerate(self.frame_start_positions)])
    

    def get_box_description(self, boxOffset, boxSize, box_type, box_data, item_id):
        if box_type == "ftyp":
            return self.get_ftyp_description(box_data)
        elif box_type == "mvhd":
            return self.get_mvhd_description(box_data)
        elif box_type == "hdlr":
            return self.get_hdlr_description(box_data)
        elif box_type == "vmhd":
            return self.get_vmhd_description(box_data)
        elif box_type == "smhd":
            return self.get_smhd_description(box_data)
        elif box_type == "dinf":
            return self.get_dinf_description(box_data)
        elif box_type == "iods":
            return self.get_iods_description(box_data)
        elif box_type == "tkhd":
            return self.get_tkhd_description(box_data)
        elif box_type == "tfhd":
            return self.get_tfhd_description(box_data)
        elif box_type == "tfdt":
            return self.get_tfdt_description(box_data)
        elif box_type == "meta":
            return self.get_meta_description(box_data)
        elif box_type == "mdat":
            return "mdat"
        elif box_type == "mdhd":
            return self.get_mdhd_description(box_data)
        elif box_type == "moov":
            return "moov"
        elif box_type == "elst":
            return self.get_elst_description(box_data)
        elif box_type == "stts":
            return self.get_stts_description(box_data)
        elif box_type == "ctts":
            return self.get_ctts_description(box_data)
        elif box_type == "stss":
            return self.get_stss_description(box_data)
        elif box_type == "stsz":
            return self.get_stsz_description(box_data)
        elif box_type == "stsc":
            return self.get_stsc_description(box_data)
        elif box_type == "stco":
            return self.get_stco_description(box_data)
        elif box_type == "sinf":
            return self.get_sinf_description(box_data)
        elif box_type == "sidx":
            return self.get_sidx_description(boxOffset, boxSize, box_data)
        elif box_type == "udta":
            return "udata"
        elif box_type == "moof":
            return self.get_moof_description(box_data)
        elif box_type == "mfhd":
            return self.get_mfhd_description(box_data)
        elif box_type == "traf":
            return self.get_traf_description(box_data)
        elif box_type == "trun":
            return self.get_trun_description( box_data, item_id)
        elif box_type == "trex":
            return self.get_trex_description(box_data)
        elif box_type == "pssh":
            return self.get_pssh_description(box_data)
        elif box_type=="saio":
            return self.get_saio_descrption(box_data)
        elif box_type == "saiz":
            return self.get_saiz_description(box_data)
        elif box_type == "senc":
            return self.get_senc_description(box_data)
        elif box_type=="tenc":
            return self.get_tenc_descrition(box_data)
        elif box_type=="mdcv":
            return self.get_mdcv_description(box_data)
        elif box_type=="esds":
            return self.get_esds_description(box_data)
        elif box_type=="hvcC":
            return self.get_hvcc_descripition(box_data)
        elif box_type=="avcC":
            return self.get_avcc_description(box_data)
        elif box_type in ('encv', 'enca'):
            return self.get_encrypted_sample_entry(box_data)
          
            
        return f"{box_type}"

    def get_ftyp_description(self, box_data):
        major_brand = box_data[:4].decode('utf-8', errors='ignore')
        minor_version = struct.unpack('>I', box_data[4:8])[0]
        compatible_brands = [box_data[i:i+4].decode('utf-8', errors='ignore') for i in range(8, len(box_data), 4)]
        return f"主品牌: {major_brand}, 次版本: {minor_version}, 兼容品牌: {', '.join(compatible_brands)}"

    def get_mvhd_description(self, box_data):
        offset = 0
        version, flags = struct.unpack(">B3s", box_data[:4])
        description = (f"Version: {version}, Flags: {flags.hex()}\n")

        offset += 4
        if version == 0:
            creation_time, modification_time = struct.unpack("<II", box_data[offset:offset+8])
            offset += 8
        elif version == 1:
            creation_time, modification_time = struct.unpack(">QQ", box_data[offset:offset+16])
            offset += 16

        creation_time = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(creation_time))
        modification_time = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(modification_time))
        
        description += (f"Creation Time: {creation_time}\n")
        description += (f"Modification Time: {modification_time}\n")
        
        self.timescale, = struct.unpack('>I', box_data[offset:offset + 4])
        offset += 4
        description += f"timescale: {self.timescale}\n"

        if version == 0:
            duration, = struct.unpack(">I", box_data[offset:offset+4])
            offset += 4
        elif version == 1:
            duration, = struct.unpack(">Q", box_data[offset:offset+8])
            offset += 8

        self.duration = duration            
        description += (f"Duration: {duration}\n")

        return description

    def get_hdlr_description(self, box_data):
        version_flags, pre_defined, handler_type = struct.unpack(">I I 4s", box_data[:12])
        if self.currentTrak and self.currentTrak.handler_type == 'unkown':
             self.currentTrak.handler_type= handler_type.decode('utf-8', errors='ignore')
        name = box_data[24:].split(b'\x00', 1)[0].decode('utf-8', 'ignore')
        return f"version: {version_flags >> 24}, flags: {version_flags & 0xFFFFFF}, handler type: {handler_type.decode('utf-8', errors='ignore')} name: {name}"

    def get_tkhd_description(self, box_data):
        offset = 0
        version, flags = struct.unpack(">B3s", box_data[:4])
        description = (f"Version: {version}, Flags: {flags.hex()}\n")

        offset += 4
        if version == 0:
            creation_time, modification_time = struct.unpack("<II", box_data[offset:offset+8])
            offset += 8
        elif version == 1:
            creation_time, modification_time = struct.unpack(">QQ", box_data[offset:offset+16])
            offset += 16

        creation_time = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(creation_time))
        modification_time = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(modification_time))
        
        description += (f"Creation Time: {creation_time}\n")
        description += (f"Modification Time: {modification_time}\n")

        track_id, = struct.unpack(">I", box_data[offset:offset+4])
        offset += 4
        description += (f"Track ID: {track_id}\n")
        
        self.currentTrak=self.get_or_create_track(track_id)

        offset += 4

        if version == 0:
            duration, = struct.unpack(">I", box_data[offset:offset+4])
            offset += 4
        elif version == 1:
            duration, = struct.unpack(">Q", box_data[offset:offset+8])
            offset += 8
        description += (f"Duration: {duration}\n")

        layer, = struct.unpack(">H", box_data[offset:offset+2])
        offset += 2
        description += (f"Layer: {layer}\n")

        alternate_group, = struct.unpack(">H", box_data[offset:offset+2])
        offset += 2
        description += (f"Alternate Group: {alternate_group}\n")

        volume, = struct.unpack(">H", box_data[offset:offset+2])
        offset += 2
        description += (f"Volume: {volume}\n")

        offset += 2

        matrix = struct.unpack("<9I", box_data[offset:offset+36])
        offset += 36
        description += (f"Matrix: {matrix}\n") 
        offset += 8
        width, height = struct.unpack(">II", box_data[offset:offset+8])
        offset += 8
        description += (f"Width: {width/(1<<16) }\n")  
        description += (f"Height: {height/(1<<16) }\n")
        
        return description
 
    def get_mdhd_description(self, box_data):
        offset = 0
        version, flags = struct.unpack(">B3s", box_data[:4])
        offset += 4
        description = f"version: {version}\n"
        if version == 0:
            creation_time, modification_time = struct.unpack("<II", box_data[offset:offset+8])
            offset += 8
        elif version == 1:
            creation_time, modification_time = struct.unpack(">QQ", box_data[offset:offset+16])
            offset += 16
            
        
        creation_time = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(creation_time))
        modification_time = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(modification_time))
        
        description += (f"Creation Time: {creation_time}\n")
        description += (f"Modification Time: {modification_time}\n")
        
        self.currentTrak.timescale, = struct.unpack(">I", box_data[offset:offset+4])
        description += (f"timescale: {self.currentTrak.timescale}\n")
        offset == 4
        duration, = struct.unpack(">I", box_data[offset:offset+4])
        description += (f"Duration: {duration}\n")
       
        return description

    def get_elst_description(self, box_data):
        version = box_data[0]
        flags = box_data[1:4]
        entry_count = struct.unpack('>I', box_data[4:8])[0]
        
        offset = 8
        
        for _ in range(entry_count):
            segment_duration, media_time, media_rate = struct.unpack('>III', box_data[offset:offset+12])
            self.currentTrak.elst.append((segment_duration, media_time, media_rate))
            offset += 12
        
        return f"entry count: {entry_count}, \nchunk: {'\n'.join(map(str, self.currentTrak.elst))}"

    def get_stts_description(self, box_data):
        entry_count = struct.unpack('>I', box_data[4:8])[0]
        sample_data = []
        frame_start_time = 0
        index = 8 
        for _ in range(entry_count):
            count, sample_delta  = struct.unpack('>II', box_data[index:index+8])
            index += 8
            self.currentTrak.stts.append((count, sample_delta ))
            sample_data.append(f"duration: {sample_delta }, count: {count}")
        return f"entry count: {entry_count} \n{'\n'.join(sample_data)}"

    def get_ctts_description(self, box_data):
        entry_count = struct.unpack('>I', box_data[4:8])[0]
        sample_data = []
        frame_start_time = 0
        index = 8 
        for _ in range(entry_count):
            count, composition_delta = struct.unpack('>II', box_data[index:index+8])
            index += 8
            self.currentTrak.ctts.append((count, composition_delta))
            sample_data.append(f"duration: {composition_delta}, count: {count}")
        return f"entry count: {entry_count}\n {'\n'.join(sample_data)}"

    def get_stss_description(self, box_data):
        entry_count = struct.unpack('>I', box_data[4:8])[0]
        index = 8
        for _ in range(entry_count):
            sync_sample = struct.unpack('>I', box_data[index:index+4])[0]
            index += 4
            self.currentTrak.stss.append(sync_sample)
        return f"sync sample count： {entry_count}  \nsync samples: {'\n'.join(map(str, self.currentTrak.stss))}"

    def get_stsz_description(self, box_data):
        verflag, sample_size = struct.unpack('>II', box_data[:8])
        sample_count = struct.unpack('>I', box_data[8:12])[0]
        offset = 12
        if sample_size == 0:
            for _ in range(sample_count):
                entry_size = struct.unpack('>I', box_data[offset:offset + 4])[0]
                self.currentTrak.stsz.append(entry_size)
                offset += 4
        else:
            self.currentTrak.stsz = [sample_size] * sample_count
        return f"sample_size:{sample_size}sample count： {sample_count} \n sizes: {'\n'.join(map(str, self.currentTrak.stsz))}"

    def get_stsc_description(self, box_data):
        entry_count = struct.unpack('>I', box_data[4:8])[0]
        offset = 8
        for _ in range(entry_count):
            first_chunk, samples_per_chunk, sample_desc_idx = struct.unpack('>III', box_data[offset:offset + 12])
            self.currentTrak.stsc.append((first_chunk, samples_per_chunk, sample_desc_idx))
            offset += 12
        return f"entry count: {entry_count}, \nchunks: {'\n'.join(map(str, self.currentTrak.stsc))}"

    def get_stco_description(self, box_data):
        entry_count = struct.unpack('>I', box_data[4:8])[0]
        offset = 8
        for _ in range(entry_count):
            chunk_offset = struct.unpack('>I', box_data[offset:offset + 4])[0]
            self.currentTrak.stco.append(chunk_offset)
            offset += 4
        return f"entry count: {entry_count} \nchunk: {'\n'.join(map(str, self.currentTrak.stco))}"

    def get_sinf_description(self, box_data):
        return "sinf"

    def get_sidx_description(self, boxOffset, boxSize, box_data):
        description = "Segment Index Box (SIDX)\n"

        version_flags, reference_ID, timescale = struct.unpack(">I I I", box_data[:12])
        version = (version_flags >> 24) & 0xFF
        flags = version_flags & 0xFFFFFF
        if version == 0:
            earliest_presentation_time, first_offset = struct.unpack(">I I", box_data[12:20])
            offset = 20
        else:
            earliest_presentation_time, first_offset = struct.unpack(">Q Q", box_data[12:28])
            offset = 28

        reserved, reference_count = struct.unpack(">H H", box_data[offset:offset + 4])
        offset += 4

        description += f"Version: {version}, reference ID: {reference_ID}, timescale: {timescale}\n"
        description += f"earliest pts: {earliest_presentation_time}, first offset: {first_offset}\n"
        description += f"refence count: {reference_count}\n"
        segmentPos = boxOffset+boxSize;
        for i in range(reference_count):
            reference_type_and_size, subsegment_duration, sap_data = struct.unpack(">I I I", box_data[offset:offset + 12])
            offset += 12

            reference_type = (reference_type_and_size >> 31) & 0x1
            reference_size = reference_type_and_size & 0x7FFFFFFF

            starts_with_SAP = (sap_data >> 31) & 0x1
            SAP_type = (sap_data >> 28) & 0x7
            SAP_delta_time = sap_data & 0x0FFFFFFF

            description += f"参考片段 {i+1}: 类型: {'I-Frame' if reference_type == 0 else 'P/B-Frame'}, startPos: {segmentPos}, 大小: {reference_size}, 持续时间: {subsegment_duration}\n"
            segmentPos += reference_size
        return description

    def get_moof_description(self, box_data):
        description = "Movie Fragment Box\n"
        offset = 0 
        file = io.BytesIO(box_data)
        while offset < len(box_data):
            box_size, box_type, box, box_header = self.read_box(file)
            description += f"子 Box 类型: {box_type}, 大小: {box_size}\n"
            if box_type == "mfhd":
                description += self.get_mfhd_description(box)
            elif box_type == "traf":
                description += self.get_traf_description( box)
            offset += box_size
        return description

    def get_iods_description(self, box_data):
        version_and_flags = struct.unpack('>I', box_data[:4])[0]
        tag = box_data[4]
        size = box_data[5]
        object_descriptor_id = struct.unpack('>H', box_data[6:8])[0]
        url_flag = box_data[8] & 0x01
        return f"version: {version_and_flags >> 24}, flags: {version_and_flags & 0xFFFFFF}, tag: {tag}, size: {size}, object descriptor ID: {object_descriptor_id}, URL flag: {url_flag}"

    def get_mfhd_description(self, box_data):
        sequence_number = struct.unpack('>I', box_data[0:4])[0]
        return f"movie sequence number: {sequence_number}"

    def get_traf_description(self, box_data):
        description = "Track Fragment Box\n"
        offset = 0
        
        while offset < len(box_data):
            box_size, box_type, box_data, box_header = self.read_box(io.BytesIO(box_data))
            description += f"子 Box 类型: {box_type}, 大小: {box_size}\n"
            if box_type == "tfhd":
                description += self.get_tfhd_description(box_data)
            elif box_type == "trun":
                description += self.get_trun_description( box_data, None)
            elif box_type == "tfdt":
                description += self.get_tfdt_description(box_data)
            offset += box_size
        return description

    def get_trun_description(self,  box_data, item_id):
        version_flags, sample_count = struct.unpack(">I I", box_data[:8])
        version = (version_flags >> 24) & 0xFF
        flags = version_flags & 0xFFFFFF

        offset = 8
        allbufferSize = 0;

        description = f"Version: {version}, sample count: {sample_count}, Flags: 0x{flags:06X}\n"

        data_offset, first_sample_flags = None, None
        if flags & 0x000001:
            data_offset = struct.unpack(">I", box_data[offset:offset+4])[0]
            offset += 4
            description += f"moof startPos: {self.moof_startPos} 数据偏移: {data_offset} \n"
            data_offset += self.moof_startPos

        if flags & 0x000004:
            first_sample_flags = struct.unpack(">I", box_data[offset:offset+4])[0]
            offset += 4
            description += f"第一帧 Flags: 0x{first_sample_flags:08X}\n"
        
        if self.currentTrak.timescale < 1:
            user_input = simpledialog.askinteger("输入timescale数值", "请输入一个整数(init mp4 中读取：")
            self.currentTrak.timescale=user_input
        description+=f"timescale:{self.currentTrak.timescale} duration:{self.currentTrak.duration}\n"
        startAddress = 0;
        sample_duration = self.currentTrak.duration
        cumulativeTime=self.currentTrak.cumulativeTime
        sample_cto=0
        frames = []
        for i in range(sample_count):
            sample_info = []
            frameInfo=FrameInfo()
            
            if flags & 0x000100:
                sample_duration = struct.unpack(">I", box_data[offset:offset+4])[0]
                offset += 4
            else:
                sample_duration=self.currentTrak.duration

            sample_info.append(f"duration: {sample_duration}")
            frameInfo.duration=sample_duration
            if flags & 0x000200:
                sample_size = struct.unpack(">I", box_data[offset:offset+4])[0]
                offset += 4
                sample_info.append(f"offset: {data_offset} size: {sample_size} 字节")
                frameInfo.size = sample_size
                frameInfo.offset=data_offset
                data_offset += sample_size
                allbufferSize+=sample_size

            if flags & 0x000400:
                sample_flags = struct.unpack(">I", box_data[offset:offset+4])[0]
                offset += 4
                sample_info.append(f"Flags: 0x{sample_flags:08X}")
                frameInfo.flags=sample_flags

            if flags & 0x000800:
                sample_cto = struct.unpack(">i", box_data[offset:offset+4])[0]
                offset += 4
                sample_info.append(f"time delta: {sample_cto}")
                
            samplePresentationTime = cumulativeTime + sample_cto - 0
            cumulativeTime += sample_duration;
            pts = samplePresentationTime/self.currentTrak.timescale
            sample_info.append(f"pts:{pts}")
            frameInfo.pts = pts
            frames.append(frameInfo)

            description += f"sample {i+1}: {', '.join(sample_info)}\n"
        description += f" bufferSize: {allbufferSize}"
        description +=f" truns: {len(frames)}\n"
        self.currentTrak.cumulativeTime=cumulativeTime
        if item_id != None:
            self.truns[item_id] = frames
            self.trunItems.append(item_id)
        return description

    def get_or_create_track(self, track_id):
        for track in self.tracks:
            if track.trackID == track_id:
                return track

        print(f"创建新轨道: {track_id}")
        track = TRACK()
        track.trackID=track_id
        track.handler_type == 'unkown'
        self.tracks.append(track)
        return track

    def get_trex_description(self, box_data):
        offset = 0
        version_flags = struct.unpack(">I", box_data[offset:offset+4])[0]
        track_id = struct.unpack(">I", box_data[offset+4:offset+8])[0]
        default_sample_description_index = struct.unpack(">I", box_data[offset+8:offset+12])[0]
        default_sample_duration = struct.unpack(">I", box_data[offset+12:offset+16])[0]
        default_sample_size = struct.unpack(">I", box_data[offset+16:offset+20])[0]
        default_sample_flags = struct.unpack(">I", box_data[offset+20:offset+24])[0]
        
        description = f"track_id: {track_id}"
        description += f"default_sample_description_index: {default_sample_description_index}\n"
        description += f"default_sample_duration: {default_sample_duration}\n"
        if self.currentTrak is None:
            self.currentTrak = self.get_or_create_track(track_id)
        self.currentTrak.trackID = track_id
        self.currentTrak.duration = default_sample_duration
        self.currentTrak.timescale = self.timescale
        description += f"default_sample_size: {default_sample_size}\n"
        description += f"default_sample_flags: {default_sample_flags}\n"
        
        return description

    def get_pssh_description(self, box_data):
        offset = 0
        version = box_data[offset+8]
        flags = box_data[offset+9:offset+12]
        system_id = uuid.UUID(bytes=box_data[offset+12:offset+28])
        cursor = offset + 28

        kids = []
        if version == 1:
            kid_count = struct.unpack(">I", box_data[cursor:cursor+4])[0]
            cursor += 4
            for _ in range(kid_count):
                kid = uuid.UUID(bytes=box_data[cursor:cursor+16])
                kids.append(str(kid))
                cursor += 16

        data_size = struct.unpack(">I", box_data[cursor:cursor+4])[0]
        cursor += 4
        pssh_data = box_data[cursor:cursor+data_size]

        description = f"system_id: {system_id}\n"
        description += f"kids: {kids}\n"
        description += f"data: {box_data}\n"
        return description

    def get_saiz_description(self, box_data):
        offset = 0
        start = offset

        version_flags = struct.unpack(">I", box_data[offset:offset+4])[0]
        version = (version_flags >> 24) & 0xFF
        flags = version_flags & 0xFFFFFF
        offset += 4

        if flags & 1:
            aux_info_type = struct.unpack(">I", box_data[offset:offset+4])[0]
            aux_info_param = struct.unpack(">I", box_data[offset+4:offset+8])[0]
            offset += 8
        else:
            aux_info_type = None
            aux_info_param = None

        default_sample_info_size = struct.unpack(">B", box_data[offset:offset+1])[0]
        offset += 1

        sample_count = struct.unpack(">I", box_data[offset:offset+4])[0]
        offset += 4

        sample_sizes = []
        if default_sample_info_size == 0:
            for _ in range(sample_count):
                sz = struct.unpack(">B", box_data[offset:offset+1])[0]
                sample_sizes.append(sz)
                offset += 1
        else:
            sample_sizes = [default_sample_info_size] * sample_count

        description = f"version: {version}\n"
        description += f"flags: {flags}\n"
        description += f"aux_info_type: {aux_info_type}\n"
        description += f"aux_info_param: {aux_info_param}\n"
        description += f"default_sample_info_size: {default_sample_info_size}\n"
        description += f"sample_count: {sample_count}\n"
        description += f"sample_sizes: {sample_sizes}\n"
        description += f"parsed_bytes: {offset - start}\n"
        
        return description

    def get_saio_descrption(self, box_data):
        offset = 0
        start = offset

        version_flags = struct.unpack(">I", box_data[offset:offset+4])[0]
        version = (version_flags >> 24) & 0xFF
        flags = version_flags & 0xFFFFFF
        offset += 4

        if flags & 1:
            aux_info_type = struct.unpack(">I", box_data[offset:offset+4])[0]
            aux_info_param = struct.unpack(">I", box_data[offset+4:offset+8])[0]
            offset += 8
        else:
            aux_info_type = None
            aux_info_param = None

        entry_count = struct.unpack(">I", box_data[offset:offset+4])[0]
        offset += 4

        offsets = []
        for _ in range(entry_count):
            if version == 0:
                val = struct.unpack(">I", box_data[offset:offset+4])[0]
                offset += 4
            else:
                val = struct.unpack(">Q", box_data[offset:offset+8])[0]
                offset += 8
            offsets.append(val)

        description = f"version: {version}\n"
        description += f"flags: {flags}\n"
        description += f"aux_info_type: {aux_info_type}\n"
        description += f"aux_info_param: {aux_info_param}\n"
        description += f"entry_count: {entry_count}\n"
        description += f"offsets: {offsets}\n"
        description += f"parsed_bytes: {offset - start}\n"
        
        return description

    def get_senc_description(self, box_data):
        offset = 0
        start = offset
       
        version_flags = struct.unpack(">I", box_data[offset:offset+4])[0]
        version = (version_flags >> 24) & 0xFF
        flags = version_flags & 0xFFFFFF
        offset += 4
        description = f"version: {version} flags: {flags}\n"
        
        sample_count = struct.unpack(">I", box_data[offset:offset+4])[0]
        offset += 4
        description += f"sample_count: {sample_count}\n"
        samples = []

        for i in range(sample_count):
            iv = box_data[offset:offset+8]
            offset += 8
            sample_entry = {
                'index': i,
                'iv': iv.hex(),
            }
            if flags & 0x02:
                subsample_count = struct.unpack(">H", box_data[offset:offset+2])[0]
                offset += 2
                subsamples = []
                for _ in range(subsample_count):
                    if offset + 6 > len(box_data):
                        return description
                    clear, encrypted = struct.unpack(">HI", box_data[offset:offset+6])
                    offset += 6
                    subsamples.append({'clear': clear, 'encrypted': encrypted})
                    description += f"iv: {iv} clear: {clear} encrypted: {encrypted}\n"
                sample_entry['subsamples'] = subsamples
            samples.append(sample_entry)
        return description

    def get_tfhd_description(self, box_data):
        version_and_flags = box_data[:4]
        version = version_and_flags[0]
        flags = int.from_bytes(version_and_flags[1:4], byteorder='big')
        
        track_id = struct.unpack('>I', box_data[4:8])[0]
        description = f"track ID: {track_id}, flags: {flags}\n"
   
        self.currentTrak = self.get_or_create_track(track_id)

        if flags & 0x000001:
            base_data_offset = struct.unpack(">Q", box_data[8:8+8])[0]
            description =+ f"base_data_offset:{base_data_offset}\n"
        if flags & 0x000002:
            sample_description_index = struct.unpack(">I", box_data[8:8+4])[0]
            description +=f"sample_description_index: {sample_description_index}\n"
        if flags & 0x000008:
            default_sample_duration = struct.unpack('>I', box_data[8:12])[0]
            if self.currentTrak.duration < 1:
                self.currentTrak.duration = default_sample_duration
            description += f", default sample duration: {default_sample_duration}\n"
        if flags & 0x000010:
            default_sample_size = struct.unpack(">I", box_data[8:8+4])[0]
            description+=f"default_sample_size: {default_sample_size}\n"
        if flags & 0x000020:
            default_sample_size = struct.unpack('>I', box_data[12:16])[0]
            description += f", 默认样本大小: {default_sample_size}"
            
        return description

    def get_tfdt_description(self, box_data):
        offset=0
        version_flags = struct.unpack(">I", box_data[offset:offset+4])[0]
        version = (version_flags >> 24) & 0xFF
        
        flags = version_flags & 0xFFFFFF
        offset += 4
        description = f"version: {version} flags: {flags}\n"
        base_decode_time = 0
        if version == 1:
            base_decode_time = struct.unpack(">Q", box_data[offset:offset+8])[0]
            offset += 8
        else:
            base_decode_time = struct.unpack(">I", box_data[offset:offset+4])[0]
            offset += 4

        description += f"base_decode_time: {base_decode_time}\n"
        
        return description

    def get_vmhd_description(self, box_data):
        version, flags, graphicsmode, red, green, blue = struct.unpack(">B3s2H2H", box_data)
        return f"version: {version}, flags: {flags}, graphics mode: {graphicsmode}, opcolor: ({red}, {green}, {blue})"

    def get_smhd_description(self, box_data):
        return "Sound Media Header Box (SMHD)"

    def get_dinf_description(self, box_data):
        return "Data Information Box (DINF)"

    def get_meta_description(self, box_data):
        return "Meta Box (META)"

    def get_ilst_description(self, box_data):
        return "Item List Box (ILST)"

    def get_esds_description(self, box_data):
        pos = 0
        version = box_data[pos]
        pos += 1
        flags = box_data[pos:pos+3]
        pos += 3
        
        descriptor_tag = box_data[pos]
        pos += 1
    
        descriptor_length = 0
        while True:
            b = box_data[pos]
            pos += 1
            descriptor_length = (descriptor_length << 7) | (b & 0x7f)
            if not (b & 0x80):
                break
        description=f"ES_Descriptor Length: {descriptor_length} bytes\n"
        
        es_id = struct.unpack(">H", box_data[pos:pos+2])[0]
        description+=f"ES_ID: {es_id}\n"
        pos += 2
        
        stream_priority = box_data[pos]
        description+=f"Stream Priority: {stream_priority}\n"
        pos += 1
        
        dec_config_tag = box_data[pos]
        description+=f"\nDecoderConfigDescriptor Tag: 0x{dec_config_tag:02x}\n"
        pos += 1
        
        dec_config_length = 0
        while True:
            b = box_data[pos]
            pos += 1
            dec_config_length = (dec_config_length << 7) | (b & 0x7f)
            if not (b & 0x80):
                break
        description+=f"DecoderConfigDescriptor Length: {dec_config_length} bytes\n"
        
        object_type = box_data[pos]
        description+=f"Object Type: 0x{object_type:02x} (AAC LC = 0x40)\n"
        pos += 1
        
        stream_type = box_data[pos]
        description+=f"Stream Type: 0x{stream_type:02x} (Audio)\n"
        pos += 1
        
        buffer_size = struct.unpack(">I", b'\x00' + box_data[pos:pos+3])[0]
        description+=f"Buffer Size: {buffer_size} bytes\n"
        pos += 3
        
        max_bitrate = struct.unpack(">I", box_data[pos:pos+4])[0]
        description+=f"Max Bitrate: {max_bitrate} bps\n"
        pos += 4
        
        avg_bitrate = struct.unpack(">I", box_data[pos:pos+4])[0]
        description+=f"Avg Bitrate: {avg_bitrate} bps\n"
        pos += 4
        
        dec_specific_tag = box_data[pos]
        description+=f"\nDecoderSpecificInfo Tag: 0x{dec_specific_tag:02x}\n"
        pos += 1
        
        dec_specific_length = 0
        while True:
            b = box_data[pos]
            pos += 1
            dec_specific_length = (dec_specific_length << 7) | (b & 0x7f)
            if not (b & 0x80):
                break
        description+=f"DecoderSpecificInfo Length: {dec_specific_length} bytes\n"
        
        if dec_specific_length >= 2:
            audio_config = box_data[pos:pos+2]
            pos += 2
            
            audio_object_type = (audio_config[0] >> 3) & 0x1f
            sampling_freq_index = ((audio_config[0] & 0x07) << 1) | ((audio_config[1] >> 7) & 0x01)
            channel_config = (audio_config[1] >> 3) & 0x0f
            
            description+=f"\nAAC Audio Specific Config:\n"
            description += f"Audio Object Type: {audio_object_type} (AAC LC = 2)\n"
            description+= f"Sampling Frequency Index: {sampling_freq_index}\n"
            description+=f"Channel Configuration: {channel_config}\n"
            
        return description

    def get_tenc_descrition(self, box_data):
        if len(box_data) < 24: return
            
        encrypted_flags = box_data[0]
        is_encrypted = (encrypted_flags >> 7) & 0x01
        iv_size = encrypted_flags & 0x0F
        if iv_size not in [0, 8, 16]:
            print(f"⚠️ 异常IV大小: {iv_size} (标准值为0/8/16)")
        
        kid = box_data[5:21].hex()
        
        return (f"""
        加密: {'是' if is_encrypted else '否'}
        IV大小: {iv_size} bytes
        KID: {kid}
        附加数据: {box_data[34:].decode('ascii', errors='replace')}
        """)

    def get_mdcv_description(self, box_data):
        if len(box_data) < 24:
            print("not engouh mdcv data")
            return "not data"
    
        def parse_chromaticity(byte_pair):
            value = struct.unpack('>H', byte_pair)[0]
            return round(value / 50000, 3)
        
        def parse_luminance(byte_quad):
            value = struct.unpack('>I', byte_quad)[0]
            return round(value / 10000, 4)
        
        r_x = parse_chromaticity(box_data[0:2])
        r_y = parse_chromaticity(box_data[2:4])
        g_x = parse_chromaticity(box_data[4:6])
        g_y = parse_chromaticity(box_data[6:8])
        b_x = parse_chromaticity(box_data[8:10])
        b_y = parse_chromaticity(box_data[10:12])
        w_x = parse_chromaticity(box_data[12:14])
        w_y = parse_chromaticity(box_data[14:16])
        max_lum = parse_luminance(box_data[16:20])
        min_lum = parse_luminance(box_data[20:24])
        
        desc = f"""Mastering Display Color Volume
        --------------------------
        Red Primary:   ({r_x:.3f}, {r_y:.3f})
        Green Primary: ({g_x:.3f}, {g_y:.3f})
        Blue Primary:  ({b_x:.3f}, {b_y:.3f})
        White Point:   ({w_x:.3f}, {w_y:.3f})
        Luminance:     {min_lum:.4f} ~ {max_lum:.4f} nits
        """
        return desc

    def get_hvcc_descripition(self, box_data ):
        self.currentTrak.codec_type = "hvcc";
        if len(box_data) < 23:  
            return
        hvcc_data = box_data[0:]
        config_version = hvcc_data[0]
        profile_space = (hvcc_data[1] >> 6) & 0x03
        tier_flag = (hvcc_data[1] >> 5) & 0x01
        profile_idc = hvcc_data[1] & 0x1F
        profile_compatibility = struct.unpack('>I', b'\x00' + hvcc_data[2:5])[0]
        level_idc = hvcc_data[5]
        min_spatial_segmentation = struct.unpack('>H', hvcc_data[6:8])[0] & 0x0FFF
        parallelism_type = hvcc_data[8] & 0x03
        chroma_format = hvcc_data[9] & 0x03
        bit_depth_luma = (hvcc_data[10] & 0x07) + 8
        bit_depth_chroma = (hvcc_data[11] & 0x07) + 8
        avg_frame_rate = struct.unpack('>H', hvcc_data[12:14])[0]
        
        num_arrays = hvcc_data[22]
        pos = 23
        vps_list, sps_list, pps_list = [], [], []
        for _ in range(num_arrays):
            if pos + 3 > len(hvcc_data):
                break
                
            array_type = hvcc_data[pos] & 0x3F
            num_units = struct.unpack('>H', hvcc_data[pos+1:pos+3])[0]
            pos += 3
            
            for _ in range(num_units):
                if pos + 2 > len(hvcc_data):
                    break
                unit_size = struct.unpack('>H', hvcc_data[pos:pos+2])[0]
                pos += 2
                if pos + unit_size > len(hvcc_data):
                    break
                    
                unit_data = hvcc_data[pos:pos+unit_size]
                if array_type == 0x20:  
                    vps_list.append(unit_data)
                elif array_type == 0x21:  
                    sps_list.append(unit_data)
                elif array_type == 0x22:  
                    pps_list.append(unit_data)
                pos += unit_size
                
        desc = f"HEVC Configuration Box\n" \
               f"Version: {config_version}\n" \
               f"Profile: space={profile_space} tier={tier_flag} idc={profile_idc}\n" \
               f"Compatibility: {profile_compatibility:032b}\n" \
               f"Level: {level_idc}\n" \
               f"Chroma: {chroma_format} ({['mono','4:2:0','4:2:2','4:4:4'][chroma_format]})\n" \
               f"Bit Depth: Luma={bit_depth_luma}, Chroma={bit_depth_chroma}\n" \
               f"VPS: {len(vps_list)}, SPS: {len(sps_list)}, PPS: {len(pps_list)}\n"
        
        if vps_list:
            desc += f"VPS: {self.to_hex(vps_list[0])}\n"
        if sps_list:
            desc += f"SPS: {self.to_hex(sps_list[0])}\n"
            desc += f"{self.parse_hevc_sps(sps_list[0])}\n"
        if pps_list:
            desc += f"PPS {self.to_hex(pps_list[0])}\n"
            
        return desc

    def get_avcc_description(self, box_data):  
        data = box_data[0:]
        self.currentTrak.codec_type = "avcc";
        if len(data) < 10: return
        config_version = data[0]
        profile = data[1]
        compatibility = data[2]
        level = data[3]
        nalu_size = (data[4] & 0x03) + 1
        sps_count = data[5] & 0x1F

        sps_list = []
        pos = 6
        for _ in range(sps_count):
            if pos + 2 > len(data): break
            sps_len = struct.unpack('>H', data[pos:pos+2])[0]
            pos += 2
            if pos + sps_len > len(data): break
            sps_list.append(data[pos:pos+sps_len])
            pos += sps_len

        pps_count = data[pos] if pos < len(data) else 0
        pos += 1
        pps_list = []
        for _ in range(pps_count):
            if pos + 2 > len(data): break
            pps_len = struct.unpack('>H', data[pos:pos+2])[0]
            pos += 2
            if pos + pps_len > len(data): break
            pps_list.append(data[pos:pos+pps_len])
            pos += pps_len

        desc = f"""AVC Configuration Box
        Version: {config_version}
        Profile: {profile} ({"Baseline" if profile==66 else "Main" if profile==77 else "High"})
        Level: {level/10:.1f}
        SPS: {len(sps_list)}, PPS: {len(pps_list)}\n"""
        
        if sps_list:
            desc +=f"SPS: {self.to_hex(sps_list[0])}\n"
            sps_info = self.parse_sps(sps_list[0])
            desc += f"sps_info:\n{sps_info}\n"
        if pps_list:
            desc+=f"PPS: {self.to_hex(pps_list[0])}\n"
            pps_info = self.parse_pps(pps_list[0])
            desc+=f"pps_info:\n{pps_info}\n"
        return desc

    def parse_stsd_box(self, box_type, box_size, box_data, offset, description, hex_data, item_id):
        start_address = f"{offset:d}"
        version_and_flags = struct.unpack('>I', box_data[:4])[0]
        entry_count = struct.unpack('>I', box_data[4:8])[0]
      
        description = f"Sample Description Box\nVersion: {(version_and_flags >> 24) & 0xFF}\n" \
                     f"Flags: {version_and_flags & 0xFFFFFF}\nEntry Count: {entry_count}"
        self.tree.item(item_id, values=(box_type, start_address, box_size, description))
        box_data = box_data[8:]
        nested_offset = offset + 16
        entry_offset = nested_offset
        remaining_data = box_data
        for i in range(entry_count):
            if len(remaining_data) < 8:
                break
                
            entry_size = struct.unpack('>I', remaining_data[:4])[0]
            entry_type = remaining_data[4:8].decode('ascii')
            entry_desc = f"Sample Entry {i+1}\nType: {entry_type}\nSize: {entry_size}"
            entry_id = self.tree.insert(item_id, "end", text=f"{entry_type} Box", 
                                      values=(entry_type, f"{entry_offset}", entry_size))
            self.box_descriptions[entry_id] = entry_desc  
            self.box_hex_data[entry_id] = self.get_hex_data(remaining_data[:entry_size], box_type) 
            
            if len(remaining_data) >= entry_size:
                self.parse_sample_entry(entry_type, remaining_data[:entry_size], entry_offset, entry_id)
                
            remaining_data = remaining_data[entry_size:]
            entry_offset += entry_size
            
        self.box_descriptions[item_id] = description  
        self.box_hex_data[item_id] = hex_data 

    def parse_sample_entry(self, entry_type, entry_data, offset, parent_id):
        if len(entry_data) < 16:
            return
      
        reserved = struct.unpack('>6B', entry_data[8:14])
        data_reference_index = struct.unpack('>H', entry_data[14:16])[0]
        
        base_desc = f"Data Reference Index: {data_reference_index}\nReserved: {reserved}"
        
        if entry_type in ['avc1', 'hvc1', 'hev1']:
            self.parse_video_sample_entry(entry_type, entry_data, offset, parent_id, base_desc)
        elif entry_type in ['mp4a', 'enca']:
            self.parse_audio_sample_entry(entry_type, entry_data, offset, parent_id, base_desc)
        elif entry_type == 'encv': 
            self.parse_encv_sample_entry(entry_data, offset, parent_id, base_desc)
        else:
            desc = f"{base_desc}\nUnknown Sample Entry Type: {entry_type}"
            self.tree.item(parent_id, values=(self.tree.item(parent_id, 'values')[0], 
                                          self.tree.item(parent_id, 'values')[1], 
                                          self.tree.item(parent_id, 'values')[2], 
                                          desc))
            if len(entry_data) > 16:
                self.read_nested_boxes(io.BytesIO(entry_data[16:]), offset + 16, parent_id)

    def parse_encv_sample_entry(self, entry_data, offset, parent_id, base_desc):
        if len(entry_data) < 78:  
            return
        entry_data = entry_data[16:]
        width, height = struct.unpack('>HH', entry_data[16:20])

        horizres, vertres = struct.unpack('>II', entry_data[20:28])

        frame_count = entry_data[28]
        depth = entry_data[61]
        desc = f"{base_desc}\nEncoded Video Sample Entry\n" \
               f"Width: {width}, Height: {height}\n" \
               f"Resolution: {horizres/0x10000:.2f}x{vertres/0x10000:.2f}\n" \
               f"Frame Count: {frame_count}\n" \
               f"Depth: {depth}\n"
        self.box_descriptions[parent_id] = desc;
        
        self.tree.item(parent_id, values=(self.tree.item(parent_id, 'values')[0], 
                                      self.tree.item(parent_id, 'values')[1], 
                                      self.tree.item(parent_id, 'values')[2], 
                                      desc))
        
        if len(entry_data) > 70:
            remaining_data = entry_data[70:]
            if len(remaining_data) >= 8 and remaining_data[4:8] == b'sinf':
                self.parse_sinf_box(remaining_data, offset + 78, parent_id)
            else:
                self.read_nested_boxes(io.BytesIO(remaining_data), offset + 78, parent_id)

    def parse_video_sample_entry(self, entry_type, entry_data, offset, parent_id, base_desc):
        if len(entry_data) < 86:
            return
            
        video_info = struct.unpack('>16H', entry_data[16:48])
        width, height = video_info[0], video_info[1]
        horizres, vertres = struct.unpack('>2I', entry_data[48:56])
        frame_count = entry_data[56]
        depth = entry_data[89]
        desc = f"{base_desc}\nVideo Sample Entry\n" \
               f"Width: {width}, Height: {height}\n" \
               f"Resolution: {horizres/0x10000}x{vertres/0x10000}\n" \
               f"Frame Count: {frame_count}\n" \
               f"Depth: {depth}"
        
        self.tree.item(parent_id, values=(self.tree.item(parent_id, 'values')[0], 
                                        self.tree.item(parent_id, 'values')[1], 
                                        self.tree.item(parent_id, 'values')[2], 
                                        desc))
        
        if len(entry_data) > 86:
            self.read_nested_boxes(io.BytesIO(entry_data[86:]), offset + 86, parent_id)

    def parse_audio_sample_entry(self, entry_type, entry_data, offset, parent_id, base_desc):
        if len(entry_data) < 28:
            return
        version = struct.unpack('>H', entry_data[16:18])[0]
        revision = struct.unpack('>H', entry_data[18:20])[0]
        vendor = struct.unpack('>I', entry_data[20:24])[0]
        channels, sample_size = struct.unpack('>HH', entry_data[24:28])
        compression_id = struct.unpack('>H', entry_data[28:30])[0]
        packet_size = struct.unpack('>H', entry_data[30:32])[0]
        sample_rate = struct.unpack('>I', entry_data[32:36])[0] >> 16
        
        desc = f"{base_desc}\nAudio Sample Entry\n" \
               f"Version: {version}, Revision: {revision}\n" \
               f"Vendor: {vendor}\n" \
               f"Channels: {channels}, Sample Size: {sample_size} bits\n" \
               f"Compression ID: {compression_id}\n" \
               f"Packet Size: {packet_size}\n" \
               f"Sample Rate: {sample_rate} Hz"
        
        self.tree.item(parent_id, values=(self.tree.item(parent_id, 'values')[0], 
                                        self.tree.item(parent_id, 'values')[1], 
                                        self.tree.item(parent_id, 'values')[2], 
                                        desc))
        
        if len(entry_data) > 36:
            self.read_nested_boxes(io.BytesIO(entry_data[36:]), offset + 36, parent_id)

    def parse_sps(self, sps_data):
        if len(sps_data) < 4 or sps_data[0] != 0x67:
            return {'error':'no data'}

        reader = BitReader(sps_data)

        forbidden_zero = reader.read_bit()
        nal_ref_idc = reader.read_bits(2)
        nal_unit_type = reader.read_bits(5)

        sps = {
            'profile_idc': reader.read_bits(8),
            'constraint_flags': reader.read_bits(8),
            'level_idc': reader.read_bits(8),
            'seq_parameter_set_id': reader.read_ue(),
        }

        if sps['profile_idc'] in [100, 110, 122, 244, 44, 83, 86, 118, 128]:
            sps['chroma_format_idc'] = reader.read_ue()
            if sps['chroma_format_idc'] == 3:
                sps['separate_colour_plane_flag'] = reader.read_bit()
            sps['bit_depth_luma'] = reader.read_ue() + 8
            sps['bit_depth_chroma'] = reader.read_ue() + 8
            sps['qpprime_y_zero_transform_bypass_flag'] = reader.read_bit()
            sps['seq_scaling_matrix_present_flag'] = reader.read_bit()
            if sps['seq_scaling_matrix_present_flag']:
                raise NotImplementedError("Scaling matrix not implemented")
        
        sps['log2_max_frame_num'] = reader.read_ue() + 4
        sps['pic_order_cnt_type'] = reader.read_ue()

        if sps['pic_order_cnt_type'] == 0:
            sps['log2_max_pic_order_cnt_lsb'] = reader.read_ue() + 4
        elif sps['pic_order_cnt_type'] == 1:
            sps['delta_pic_order_always_zero_flag'] = reader.read_bit()
            sps['offset_for_non_ref_pic'] = reader.read_se()
            sps['offset_for_top_to_bottom_field'] = reader.read_se()
            sps['num_ref_frames_in_pic_order_cnt_cycle'] = reader.read_ue()
            sps['offset_for_ref_frame'] = [
                reader.read_se() for _ in range(sps['num_ref_frames_in_pic_order_cnt_cycle'])
            ]

        sps['max_num_ref_frames'] = reader.read_ue()
        sps['gaps_in_frame_num_value_allowed_flag'] = reader.read_bit()

        sps['pic_width_in_mbs'] = reader.read_ue() + 1
        sps['pic_height_in_map_units'] = reader.read_ue() + 1
        sps['frame_mbs_only_flag'] = reader.read_bit()

        if not sps['frame_mbs_only_flag']:
            sps['mb_adaptive_frame_field_flag'] = reader.read_bit()

        sps['direct_8x8_inference_flag'] = reader.read_bit()

        sps['width'] = sps['pic_width_in_mbs'] * 16
        sps['height'] = sps['pic_height_in_map_units'] * 16 * (2 - sps['frame_mbs_only_flag'])

        sps['vui_parameters_present_flag'] = reader.read_bit()
        if sps['vui_parameters_present_flag']:
            sps.update(self.parse_vui_parameters(reader))
        return sps
    
    def parse_hevc_sps(self,sps_data):
        reader = BitReader(sps_data)

        nalu_header = reader.read_bits(16)

        sps = {
            'video_parameter_set_id': reader.read_bits(4),
            'max_sub_layers': reader.read_bits(3),
            'temporal_id_nesting_flag': reader.read_bit()
        }
        sps.update(self.parse_hevc_profile_tier_level(reader, sps['max_sub_layers']))

        sps['seq_parameter_set_id'] = reader.read_ue()
        sps['chroma_format_idc'] = reader.read_ue()

        if sps['chroma_format_idc'] == 3:
            sps['separate_colour_plane_flag'] = reader.read_bit()

        sps['pic_width_in_luma_samples'] = reader.read_ue()
        sps['pic_height_in_luma_samples'] = reader.read_ue()

        sps['width'] = sps['pic_width_in_luma_samples']
        sps['height'] = sps['pic_height_in_luma_samples']

        return sps

    def parse_vui_parameters(sefl, reader):
        vui = {}
        vui['aspect_ratio_info_present_flag'] = reader.read_bit()
        if vui['aspect_ratio_info_present_flag']:
            vui['aspect_ratio_idc'] = reader.read_bits(8)
            if vui['aspect_ratio_idc'] == 255:  # Extended_SAR
                vui['sar_width'] = reader.read_bits(16)
                vui['sar_height'] = reader.read_bits(16)

        vui['overscan_info_present_flag'] = reader.read_bit()
        if vui['overscan_info_present_flag']:
            vui['overscan_appropriate_flag'] = reader.read_bit()

        vui['video_signal_type_present_flag'] = reader.read_bit()
        if vui['video_signal_type_present_flag']:
            vui['video_format'] = reader.read_bits(3)
            vui['video_full_range_flag'] = reader.read_bit()
            vui['colour_description_present_flag'] = reader.read_bit()
            if vui['colour_description_present_flag']:
                vui['colour_primaries'] = reader.read_bits(8)
                vui['transfer_characteristics'] = reader.read_bits(8)
                vui['matrix_coefficients'] = reader.read_bits(8)

        vui['chroma_loc_info_present_flag'] = reader.read_bit()
        if vui['chroma_loc_info_present_flag']:
            vui['chroma_sample_loc_type_top_field'] = reader.read_ue()
            vui['chroma_sample_loc_type_bottom_field'] = reader.read_ue()

        vui['timing_info_present_flag'] = reader.read_bit()
        if vui['timing_info_present_flag']:
            vui['num_units_in_tick'] = reader.read_bits(32)
            vui['time_scale'] = reader.read_bits(32)
            vui['fixed_frame_rate_flag'] = reader.read_bit()
            if vui['num_units_in_tick'] > 0 and vui['time_scale'] > 0:
                vui['frame_rate'] = vui['time_scale'] / (2 * vui['num_units_in_tick'])

        return vui
    
    def parse_pps(self, pps_data):
        if len(pps_data) < 2 or pps_data[0] != 0x68:
            return {'error': 'no data'}

        reader = BitReader(pps_data)

        forbidden_zero = reader.read_bit()
        nal_ref_idc = reader.read_bits(2)
        nal_unit_type = reader.read_bits(5)

        pps = {
            'pic_parameter_set_id': reader.read_ue(),
            'seq_parameter_set_id': reader.read_ue(),
            'entropy_coding_mode_flag': reader.read_bit(),
            'bottom_field_pic_order_in_frame_present_flag': reader.read_bit(),
            'num_slice_groups': reader.read_ue(),
        }

        if pps['num_slice_groups'] > 1:
            pps['slice_group_map_type'] = reader.read_ue()
            # 更详细的slice group映射解析省略...

        pps['num_ref_idx_l0_active'] = reader.read_ue() + 1
        pps['num_ref_idx_l1_active'] = reader.read_ue() + 1
        pps['weighted_pred_flag'] = reader.read_bit()
        pps['weighted_bipred_idc'] = reader.read_bits(2)
        pps['pic_init_qp'] = reader.read_se() + 26
        pps['pic_init_qs'] = reader.read_se() + 26
        pps['chroma_qp_index_offset'] = reader.read_se()
        pps['deblocking_filter_control_present_flag'] = reader.read_bit()
        pps['constrained_intra_pred_flag'] = reader.read_bit()
        pps['redundant_pic_cnt_present_flag'] = reader.read_bit()

        return pps

    def parse_hevc_profile_tier_level(self, reader, max_sub_layers):
        ptl = {
            'general_profile_space': reader.read_bits(2),
            'general_tier_flag': reader.read_bit(),
            'general_profile_idc': reader.read_bits(5),
            'general_profile_compatibility_flags': reader.read_bits(32),
            'general_constraint_indicator_flags': reader.read_bits(48),
            'general_level_idc': reader.read_bits(8)
        }
        
        ptl['sub_layer_profile_present_flag'] = [reader.read_bit() for _ in range(max_sub_layers)]
        ptl['sub_layer_level_present_flag'] = [reader.read_bit() for _ in range(max_sub_layers)]
        
        for i in range(max_sub_layers):
            if ptl['sub_layer_profile_present_flag'][i]:
                ptl[f'sub_layer_{i}_profile_space'] = reader.read_bits(2)
                ptl[f'sub_layer_{i}_tier_flag'] = reader.read_bit()
                ptl[f'sub_layer_{i}_profile_idc'] = reader.read_bits(5)
                ptl[f'sub_layer_{i}_profile_compatibility_flags'] = reader.read_bits(32)
                ptl[f'sub_layer_{i}_constraint_indicator_flags'] = reader.read_bits(48)
            
            if ptl['sub_layer_level_present_flag'][i]:
                ptl[f'sub_layer_{i}_level_idc'] = reader.read_bits(8)
        
        return ptl

app = None

def select_file(root):
    file_path = filedialog.askopenfilename(title="选择文件", filetypes=[("所有文件", "*.*")])
    if file_path:
        global app
        if app != None:
            app.remove_trees()
        app = MP4ParserApp(root, file_path)
        app.display_frame_info()
        
def ask_long_url(title="输入URL", prompt="请输入MP4网络流URL:", width=60):
    import tkinter as tk
    from tkinter import simpledialog

    def on_ok():
        nonlocal url
        url = entry.get()
        dialog.destroy()

    url = None
    dialog = tk.Toplevel()
    dialog.title(title)
    dialog.geometry("600x100")  # 可以根据需要调整窗口大小

    label = tk.Label(dialog, text=prompt)
    label.pack(pady=5)

    entry = tk.Entry(dialog, width=width)
    entry.pack(pady=5)
    entry.focus()

    btn = tk.Button(dialog, text="确定", command=on_ok)
    btn.pack(pady=5)

    dialog.transient()  # 设置为顶层窗口
    dialog.grab_set()
    dialog.wait_window()

    return url

def select_url(root):
    url = ask_long_url("输入URL", "请输入MP4网络流URL:",600)
    if url:
        global app
        if app != None:
            app.remove_trees()
        app = MP4ParserApp(root, url)
        app.display_frame_info()

if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("1000x600")
    try:
        root.iconbitmap("icon.ico")
    except:
        pass

    button_frame = tk.Frame(root)
    button_frame.pack(anchor="w", padx=10, pady=10)
    
    file_button = tk.Button(button_frame, text="选择本地文件", command=lambda: select_file(root))
    file_button.pack(side=tk.LEFT)
    
    url_button = tk.Button(button_frame, text="输入网络URL", command=lambda: select_url(root))
    url_button.pack(side=tk.LEFT, padx=10)

    root.mainloop()
