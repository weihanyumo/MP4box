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

class TRACK:
    def __init__(self):
        self.timescale = 0
        self.trackType = 0
        
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
        
    def calculate_frame_info(self):
        dts = 0
        dts_list = []
        pts_list = []
        offsets = []
        sizes = []
        chunk_index = 0
        sample_index = 0

        # 解码时间戳 (DTS)
        for sample_count, sample_delta in self.stts:
            for _ in range(sample_count):
                dts_list.append(dts/self.timescale)
                dts += sample_delta

        # 显示时间戳 (PTS)
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
        
        
        # 计算 chunk 偏移 
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
        # 汇总结果
        frames = []
        for i in range(len(self.stsz)):
            flag="B-Frame"
            if i+1 in self.stss:
                flag="I-Frame"
                
            frames.append({
                'DTS': dts_list[i],
                'PTS': pts_list[i],
                'size': sizes[i],
                'offset': offsets[i],
                'flag':flag
            })

        return frames
        
#MP4ParserApp
class MP4ParserApp:
    def __init__(self, root, file_path):
        self.root = root
        self.root.title("MP4 Box Parser")

        self.file_path = file_path
        self.frame_start_positions = []
        self.total_frames = 0 
        self.box_descriptions = {}  
        self.box_hex_data = {}  
        self.timescale = 1
        self.duration = 0
        self.tracks = []
        self.currentTrak = {}

        self.stss = []
        self.mdat_item_id = 0
        self.totlalFrameCount = 0;
        
        # main frame
        self.main_frame = tk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.file_label = tk.Label(self.main_frame, text=file_path, font=("Arial", 12, "bold"))
        self.file_label.pack(anchor="w")
        # 左侧 Treeview 组件
        tree_frame = tk.Frame(self.main_frame)
        tree_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(tree_frame, columns=("Type",  "Start Address", "Size","Description"))
        self.tree.heading("#0", text="Box Name", anchor="w")
        self.tree.heading("Type", text="Type", anchor="w")
        self.tree.heading("Size", text="Size (bytes)", anchor="w")
        self.tree.heading("Start Address", text="Start Address", anchor="w")
        self.tree.heading("Description", text="description", anchor="w")

        self.tree.column("#0", width=200)
        self.tree.column("Type", width=100)
        self.tree.column("Size", width=100)
        self.tree.column("Start Address", width=150)        
        self.tree.column("Description", width=300)

        self.tree.pack(fill=tk.BOTH, expand=True)

        # 绑定 Treeview 选择事件
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        # 下方两个窗口：左侧 description，右侧 hex_data
        bottom_frame = tk.Frame(self.main_frame)
        bottom_frame.pack(fill=tk.BOTH, expand=True)

        # 左侧：Description 窗口
        desc_frame = tk.Frame(bottom_frame)
        desc_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        self.description_label = tk.Label(desc_frame, text="Box Description:", font=("Arial", 12, "bold"))
        self.description_label.pack(anchor="w")

        desc_text_frame = tk.Frame(desc_frame)
        desc_text_frame.pack(fill=tk.BOTH, expand=True)

        desc_scroll_y = tk.Scrollbar(desc_text_frame, orient=tk.VERTICAL)
        self.description_text = tk.Text(
            desc_text_frame, height=10, wrap="word", font=("Arial", 10),
            yscrollcommand=desc_scroll_y.set
        )
        desc_scroll_y.config(command=self.description_text.yview)

        self.description_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        desc_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

        # 右侧：Hex Data 窗口
        hex_frame = tk.Frame(bottom_frame)
        hex_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))

        self.hex_label = tk.Label(hex_frame, text="Hex Data:", font=("Arial", 12, "bold"))
        self.hex_label.pack(anchor="w")

        hex_text_frame = tk.Frame(hex_frame)
        hex_text_frame.pack(fill=tk.BOTH, expand=True)

        # 滚动条
        hex_scroll_x = tk.Scrollbar(hex_text_frame, orient=tk.HORIZONTAL)
        hex_scroll_y = tk.Scrollbar(hex_text_frame, orient=tk.VERTICAL)

        # 文本框
        self.hex_text = tk.Text(
            hex_text_frame, height=10, wrap="none", font=("Courier", 10),
            yscrollcommand=hex_scroll_y.set, xscrollcommand=hex_scroll_x.set
        )

        # 滚动条绑定
        hex_scroll_x.config(command=self.hex_text.xview)
        hex_scroll_y.config(command=self.hex_text.yview)

        # 网格布局，保证滚动条不会互相挤压
        self.hex_text.grid(row=0, column=0, sticky="nsew")
        hex_scroll_y.grid(row=0, column=1, sticky="ns")
        hex_scroll_x.grid(row=1, column=0, sticky="ew")

        # 配置行列权重，保证可以拉伸
        hex_text_frame.grid_rowconfigure(0, weight=1)
        hex_text_frame.grid_columnconfigure(0, weight=1)
        
        self.parse_fmp4(file_path)
             
    def remove_trees(self):
        print("remove trees")
        self.main_frame.pack_forget()
        self.root.update_idletasks()  # 强制刷新界面

        
    def on_tree_select(self, event):
        selected_item = self.tree.selection()
        if selected_item:
            # 显示描述信息
            description = self.box_descriptions.get(selected_item[0], "No description available")
            if selected_item[0] == self.mdat_item_id:
                description = self.get_sample_description()
            self.description_text.delete("1.0", tk.END)
            self.description_text.insert(tk.END, description)

            # 显示 Hex 数据
            hex_data = self.box_hex_data.get(selected_item[0], "No hex data available")
            self.hex_text.delete("1.0", tk.END)
            self.hex_text.insert(tk.END, hex_data)
    
    def parse_fmp4(self, file_path):
        with open(file_path, 'rb') as file:
            offset = 0  # 追踪当前偏移量
            while True:
                box_size, box_type, box_data, box_header = self.read_box(file)
                if not box_size:
                    break  
                description = self.get_box_description(offset, box_size, box_type, box_data)
                #description = f"size: {box_size}, des: {description}"

                
                hex_data = self.get_hex_data(box_header + box_data, box_type) 
                self.add_box_to_treeview(box_type, box_size, box_data, offset, description, hex_data)
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
        
    def get_box_description(self, boxOffset, boxSize, box_type, box_data):
        if box_type == "ftyp":
            return self.get_ftyp_description(box_data)
        elif box_type == "mvhd":
            return self.get_mvhd_description(box_data)
        elif box_type == "hdlr":
            return self.get_hdlr_description(box_data, boxSize)
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
            return self.get_meta_description(box_data, boxSize)
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
            return self.get_traf_description(boxOffset, box_data)
        elif box_type == "trun":
            return self.get_trun_description(boxOffset, box_data)
        elif box_type == "trex":
            return self.get_trex_description(boxOffset, box_data)
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
        elif box_type in ('encv', 'enca'):
            return self.get_encrypted_sample_entry(box_data)
          
            
        return f"未知的 Box 类型: {box_type}"

    def get_ftyp_description(self, box_data):
        major_brand = box_data[:4].decode('utf-8', errors='ignore')
        minor_version = struct.unpack('>I', box_data[4:8])[0]
        compatible_brands = [box_data[i:i+4].decode('utf-8', errors='ignore') for i in range(8, len(box_data), 4)]
        return f"主品牌: {major_brand}, 次版本: {minor_version}, 兼容品牌: {', '.join(compatible_brands)}"

#get box des   
    def get_sample_description(self):
        description = f"track count: {len(self.tracks)}\n"
        print(f"description tracks count:{len(self.tracks)}")
        for i, track in enumerate(self.tracks):
            print(f"calculate track:{track.trackID}")
            frames = track.calculate_frame_info()
            description += f"track {i+1} frame count: {len(frames)}\n"
            for j, frame in enumerate(frames):
                description += f"Frame {j + 1}: PTS={frame['PTS']:.3f}, DTS={frame['DTS']:.3f}, Size={frame['size']}, offset={frame['offset']}, flag={frame['flag']}\n"
        return description
        
    def get_mvhd_description(self, box_data):
        """
        Version	1	版本号 (1)
        Flags	3	标志位 (通常为 0)
        Creation Time	8	创建时间 (Unix 时间戳)
        Modification Time	8	修改时间 (Unix 时间戳)
        Time Scale	4	时间刻度 (每秒的时间单位数)
        Duration	8	时长 (以时间刻度为单位的持续时间)
        Rate	4	播放速率 (通常为 0x00010000 = 1.0)
        Volume	2	音量 (通常为 0x0100 = 1.0)
        Reserved	10	保留字段
        Matrix	36	视频变换矩阵
        Pre-defined	24	预留字段
        Next Track ID	4	下一个可用的 track ID
        """
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

        # Duration (4 bytes or 8 bytes)
        if version == 0:
            duration, = struct.unpack(">I", box_data[offset:offset+4])
            offset += 4
        elif version == 1:
            duration, = struct.unpack(">Q", box_data[offset:offset+8])
            offset += 8

        self.duration = duration            
        description += (f"Duration: {duration}\n")

        return description
    
    def get_hdlr_description(self, box_data, box_length):
        """
        4   version & flags	版本号（通常为0）及标志位
        4	pre_defined	保留字段，始终为0
        4	handler_type	处理程序类型
        12	reserved	保留字段，全部为0
        n	name	处理程序名称，以 null 终止的字符串
        """    
        version_flags, pre_defined, handler_type = struct.unpack(">I I 4s", box_data[:12])
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

        # Track ID (4 bytes)
        track_id, = struct.unpack(">I", box_data[offset:offset+4])
        offset += 4
        description += (f"Track ID: {track_id}\n")
        
        self.currentTrak=self.get_or_create_track(track_id)

        # Reserved (4 bytes)
        offset += 4

        # Duration (4 bytes or 8 bytes)
        if version == 0:
            duration, = struct.unpack(">I", box_data[offset:offset+4])
            offset += 4
        elif version == 1:
            duration, = struct.unpack(">Q", box_data[offset:offset+8])
            offset += 8
        description += (f"Duration: {duration}\n")

        # Layer (2 bytes)
        layer, = struct.unpack(">H", box_data[offset:offset+2])
        offset += 2
        description += (f"Layer: {layer}\n")

        # Alternate Group (2 bytes)
        alternate_group, = struct.unpack(">H", box_data[offset:offset+2])
        offset += 2
        description += (f"Alternate Group: {alternate_group}\n")

        # Volume (2 bytes)
        volume, = struct.unpack(">H", box_data[offset:offset+2])
        offset += 2
        description += (f"Volume: {volume}\n")

        # Reserved (2 bytes)
        offset += 2

        # Matrix (9 x 4 bytes)
        matrix = struct.unpack("<9I", box_data[offset:offset+36])
        offset += 36
        description += (f"Matrix: {matrix}\n") 
        #why ?
        offset += 8
        # Width and Height (4 bytes each)
        width, height = struct.unpack(">II", box_data[offset:offset+8])
        offset += 8
        description += (f"Width: {width/(1<<16) }\n")  # Convert fixed-point 16.16 to float
        description += (f"Height: {height/(1<<16) }\n")
        
        return description
 
    def get_mdhd_description(self, box_data):
        
        """
 
        Version	1	版本号（0 或 1）
        Flags	3	标志位
        Creation Time	8	创建时间（Unix时间戳）
        Modification Time	8	修改时间（Unix时间戳）
        Time Scale	4	时间刻度（表示每秒的单位数）
        Duration	8	持续时间（以时间刻度单位计）
        Language	2	语言代码（通常是 ISO-639-2 语言代码）
        Quality	2	媒体质量（通常为0）
        """
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
        # 解析 Reference 数据
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
            #description += f"  - 从 SAP 开始: {starts_with_SAP}, SAP 类型: {SAP_type}, SAP 时间增量: {SAP_delta_time}\n"
        return description

    def get_moof_description(self, box_data):
        description = "Movie Fragment Box\n"
        offset = 0 
        while offset < len(box_data):
            box_size, box_type, box_data, box_header = self.read_box(io.BytesIO(box_data))
            description += f"子 Box 类型: {box_type}, 大小: {box_size}\n"
            if box_type == "mfhd":
                description += self.get_mfhd_description(box_data)
            elif box_type == "traf":
                description += self.get_traf_description(box_data)
            offset += box_size
        return description
    
    def get_iods_description(self, box_data):
        """
        4	version & flags	版本号（通常为 0）及标志位
        n	InitialObjectDescriptor	初始对象描述符
        """
        version_and_flags = struct.unpack('>I', box_data[:4])[0]
        tag = box_data[4]
        size = box_data[5]
        object_descriptor_id = struct.unpack('>H', box_data[6:8])[0]
        url_flag = box_data[8] & 0x01
        return f"version: {version_and_flags >> 24}, flags: {version_and_flags & 0xFFFFFF}, tag: {tag}, size: {size}, object descriptor ID: {object_descriptor_id}, URL flag: {url_flag}"
    
    def get_mfhd_description(self, box_data):
        sequence_number = struct.unpack('>I', box_data[0:4])[0]
        return f"movie sequence number: {sequence_number}"

    def get_traf_description(self,startPos, box_data):
        description = "Track Fragment Box\n"
        offset = 0
        
        while offset < len(box_data):
            box_size, box_type, box_data, box_header = self.read_box(io.BytesIO(box_data))
            description += f"子 Box 类型: {box_type}, 大小: {box_size}\n"
            if box_type == "tfhd":
                description += self.get_tfhd_description(box_data)
            elif box_type == "trun":
                description += self.get_trun_description(startPos, box_data)
            elif box_type == "tfdt":
                description += self.get_tfdt_description(box_data)
            offset += box_size
            startPos += box_size
        return description

    def get_trun_description(self,startPos,  box_data):
        #description = "Track Run Box (TRUN)\n"

        version_flags, sample_count = struct.unpack(">I I", box_data[:8])
        version = (version_flags >> 24) & 0xFF
        flags = version_flags & 0xFFFFFF

        offset = 8
        startPos += 8
        allbufferSize = 0;

        description = f"Version: {version}, sample count: {sample_count}, Flags: 0x{flags:06X}\n"

        data_offset, first_sample_flags = None, None
        if flags & 0x000001:
            data_offset = struct.unpack(">I", box_data[offset:offset+4])[0]
            offset += 4
            description += f"数据偏移: {data_offset}\n"

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
        for i in range(sample_count):
            sample_info = []
            if flags & 0x000100:
                sample_duration = struct.unpack(">I", box_data[offset:offset+4])[0]
                offset += 4
            else:
                sample_duration=self.currentTrak.duration

            sample_info.append(f"duration: {sample_duration}")
            if flags & 0x000200:
                sample_size = struct.unpack(">I", box_data[offset:offset+4])[0]
                offset += 4
                sample_info.append(f"size: {sample_size} 字节")
                self.frame_start_positions.append(startPos)
                startPos += sample_size
                allbufferSize+=sample_size

            if flags & 0x000400:
                sample_flags = struct.unpack(">I", box_data[offset:offset+4])[0]
                offset += 4
                sample_info.append(f"Flags: 0x{sample_flags:08X}")

            if flags & 0x000800:
                sample_cto = struct.unpack(">i", box_data[offset:offset+4])[0]
                offset += 4
                sample_info.append(f"time delta: {sample_cto}")
                
            samplePresentationTime = cumulativeTime + sample_cto - 0
            #edtsOffset;
            cumulativeTime += sample_duration;
            sample_info.append(f"pts:{samplePresentationTime/self.currentTrak.timescale:.3f}")

            description += f"sample {i+1}: {', '.join(sample_info)}\n"
        description += f" bufferSize: {allbufferSize}"
        self.currentTrak.cumulativeTime=cumulativeTime
        return description

    def get_or_create_track(self, track_id):
        for track in self.tracks:
            if track.trackID == track_id:
                return track

            
        track = TRACK()
        track.trackID=track_id
        self.tracks.append(track)
        return track
        
    def get_trex_description(self,startPos,  box_data):
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
        self.currentTrak.duration = default_sample_duration
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

        # Optional fields if flags & 1
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

        # Optional aux_info_type
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

    def get_meta_description(self, box_data, box_length):
        return "Meta Box (META)"
    
    def get_ilst_description(self, box_data, box_length):
        return "Item List Box (ILST)"
        
    def get_tenc_descrition(self, box_data):
        if len(box_data) < 24: return
            
        # 加密参数
        encrypted_flags = box_data[0]
        is_encrypted = (encrypted_flags >> 7) & 0x01
        iv_size = encrypted_flags & 0x0F
        
        # 打印警告
        if iv_size not in [0, 8, 16]:
            print(f"⚠️ 异常IV大小: {iv_size} (标准值为0/8/16)")
        
        # KID解析
        kid = box_data[5:21].hex()
        
        # 输出结果
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
    
        # 解析色度坐标 (u16.16格式)
        def parse_chromaticity(byte_pair):
            value = struct.unpack('>H', byte_pair)[0]
            return round(value / 50000, 3)
        
        # 解析亮度值 (u16.16格式)
        def parse_luminance(byte_quad):
            value = struct.unpack('>I', byte_quad)[0]
            return round(value / 10000, 4)
        
        # 提取数据
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
        
    def parse_hvcc(self, hvcc_data, offset, parent_id):
        """解析 HEVC 配置 (hvcC) box"""
        if len(hvcc_data) < 23:  # hvcC 最小长度
            return

        # 解析基础头信息
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
        
        # 解析 NAL 单元类型
        num_arrays = hvcc_data[22]
        pos = 23
        
        # 解析 VPS/SPS/PPS 等参数集
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
                if array_type == 0x20:  # VPS
                    vps_list.append(unit_data)
                elif array_type == 0x21:  # SPS
                    sps_list.append(unit_data)
                elif array_type == 0x22:  # PPS
                    pps_list.append(unit_data)
                pos += unit_size

        # 构建描述信息
        desc = f"HEVC Configuration Box\n" \
               f"Version: {config_version}\n" \
               f"Profile: space={profile_space} tier={tier_flag} idc={profile_idc}\n" \
               f"Compatibility: {profile_compatibility:032b}\n" \
               f"Level: {level_idc}\n" \
               f"Chroma: {chroma_format} ({['mono','4:2:0','4:2:2','4:4:4'][chroma_format]})\n" \
               f"Bit Depth: Luma={bit_depth_luma}, Chroma={bit_depth_chroma}\n" \
               f"VPS: {len(vps_list)}, SPS: {len(sps_list)}, PPS: {len(pps_list)}"

        # 添加到树形视图
        item_id = self.tree.insert(parent_id, "end", text="hvcC Box", 
                                 values=("hvcC", f"{offset}", len(hvcc_data), desc))
        
        # 可选：添加参数集详细信息
        if vps_list:
            self._add_parameter_sets(item_id, "VPS", vps_list, offset + pos)
        if sps_list:
            self._add_parameter_sets(item_id, "SPS", sps_list, offset + pos)
        if pps_list:
            self._add_parameter_sets(item_id, "PPS", pps_list, offset + pos)
        
        self.box_descriptions[item_id] = desc
        self.box_hex_data[item_id] = self.get_hex_data(hvcc_data, "hvcC")

    def _add_parameter_sets(self, parent_id, name, param_sets, base_offset):
        """添加参数集详细信息"""
        for i, data in enumerate(param_sets):
            item_id = self.tree.insert(parent_id, "end", 
                                     text=f"{name} {i+1}",
                                     values=(f"{name}", f"{base_offset}", len(data), 
                                            f"{name} {i+1} (Size: {len(data)})"))
            self.box_hex_data[item_id] = self.get_hex_data(data, name)
            base_offset += len(data)
      
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
                                      values=(entry_type, f"{entry_offset}", entry_size, entry_desc))
            self.box_descriptions[entry_id] = entry_desc  
            self.box_hex_data[entry_id] = self.get_hex_data(remaining_data[:entry_size], box_type) 
            
            if len(remaining_data) >= entry_size:
                self.parse_sample_entry(entry_type, remaining_data[:entry_size], entry_offset, entry_id)
                
            remaining_data = remaining_data[entry_size:]
            entry_offset += entry_size
            
        self.box_descriptions[item_id] = description  
        self.box_hex_data[item_id] = hex_data 
        
    def parse_sample_entry(self, entry_type, entry_data, offset, parent_id):
        """ 统一处理所有 sample entry 类型"""
        if len(entry_data) < 16:
            return
      
        # 公共头部 (8字节: size + type, 6字节保留)
        reserved = struct.unpack('>6B', entry_data[8:14])
        data_reference_index = struct.unpack('>H', entry_data[14:16])[0]
        
        base_desc = f"Data Reference Index: {data_reference_index}\nReserved: {reserved}"
        
        # 根据不同类型调用特定解析方法
        if entry_type in ['avc1', 'hvc1', 'hev1']:  # 视频
            self.parse_video_sample_entry(entry_type, entry_data, offset, parent_id, base_desc)
        elif entry_type in ['mp4a', 'enca']:  # 音频
            self.parse_audio_sample_entry(entry_type, entry_data, offset, parent_id, base_desc)
        elif entry_type == 'encv':  # 编码视频
            self.parse_encv_sample_entry(entry_data, offset, parent_id, base_desc)
        elif entry_type == 'avcC':  # AVC 配置
            self.parse_avcc(entry_data, offset, parent_id)
        elif entry_type == 'hvcC':  # HEVC 配置
            self.parse_hvcc(entry_data, offset, parent_id)
        elif entry_type == 'esds':  # ES 描述
            self.parse_esds(entry_data, offset, parent_id)
        else:
            # 未知类型的默认处理
            desc = f"{base_desc}\nUnknown Sample Entry Type: {entry_type}"
            self.tree.item(parent_id, values=(self.tree.item(parent_id, 'values')[0], 
                                          self.tree.item(parent_id, 'values')[1], 
                                          self.tree.item(parent_id, 'values')[2], 
                                          desc))
            if len(entry_data) > 16:
                self.read_nested_boxes(io.BytesIO(entry_data[16:]), offset + 16, parent_id)

    def parse_encv_sample_entry(self, entry_data, offset, parent_id, base_desc):
        """解析 encv (Encoded Video) sample entry"""
        if len(entry_data) < 78:  # encv 最小大小
            return
        print("encv entry\n")
        print(f"box len: {len(entry_data)}")
            
        # 解析视频信息
        entry_data = entry_data[16:]
        width, height = struct.unpack('>HH', entry_data[16:20])
        print(f"wh:{width} {height}")
        horizres, vertres = struct.unpack('>II', entry_data[20:28])
        print(f"hv:{horizres} {vertres}")
        frame_count = entry_data[28]
        #compressor_name = entry_data[29:61].decode('utf-8').strip('\x00')
        depth = entry_data[61]
        #codec_name = entry_data[62:78].decode('utf-8').strip('\x00')
        # 更新描述
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
        
        
        # 解析可能的保护方案信息 (sinf box) 或其他子 box
        if len(entry_data) > 70:
            remaining_data = entry_data[70:]
            if len(remaining_data) >= 8 and remaining_data[4:8] == b'sinf':
                self.parse_sinf_box(remaining_data, offset + 78, parent_id)
            else:
                self.read_nested_boxes(io.BytesIO(remaining_data), offset + 78, parent_id)

    def parse_video_sample_entry(self, entry_type, entry_data, offset, parent_id, base_desc):
        """解析视频 sample entry"""
        if len(entry_data) < 86:
            return
            
        # 视频 sample entry 的固定部分 (16字节头部 + 70字节视频信息)
        video_info = struct.unpack('>16H', entry_data[16:48])
        width, height = video_info[0], video_info[1]
        horizres, vertres = struct.unpack('>2I', entry_data[48:56])
        frame_count = entry_data[56]
        depth = entry_data[89]
        
        # 更新描述
        desc = f"{base_desc}\nVideo Sample Entry\n" \
               f"Width: {width}, Height: {height}\n" \
               f"Resolution: {horizres/0x10000}x{vertres/0x10000}\n" \
               f"Frame Count: {frame_count}\n" \
               f"Depth: {depth}"
        
        self.tree.item(parent_id, values=(self.tree.item(parent_id, 'values')[0], 
                                        self.tree.item(parent_id, 'values')[1], 
                                        self.tree.item(parent_id, 'values')[2], 
                                        desc))
        
        # 解析可能的 codec 配置 box (avcC, hvcC 等)
        if len(entry_data) > 86:
            self.read_nested_boxes(io.BytesIO(entry_data[86:]), offset + 86, parent_id)

    def parse_audio_sample_entry(self, entry_type, entry_data, offset, parent_id, base_desc):
        """解析音频 sample entry"""
        if len(entry_data) < 28:
            return
            
        # 音频 sample entry 的固定部分 (16字节头部 + 12字节音频信息)
        version = struct.unpack('>H', entry_data[16:18])[0]
        revision = struct.unpack('>H', entry_data[18:20])[0]
        vendor = struct.unpack('>I', entry_data[20:24])[0]
        channels, sample_size = struct.unpack('>HH', entry_data[24:28])
        compression_id = struct.unpack('>H', entry_data[28:30])[0]
        packet_size = struct.unpack('>H', entry_data[30:32])[0]
        sample_rate = struct.unpack('>I', entry_data[32:36])[0] >> 16
        
        # 更新描述
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
        
        # 解析可能的 codec 配置 box (esds 等)
        if len(entry_data) > 36:
            self.read_nested_boxes(io.BytesIO(entry_data[36:]), offset + 36, parent_id)

    def parse_avcc(self, data, offset, parent_id):
        if len(data) < 10: return
        
        # 解析基础头信息
        config_version = data[0]
        profile = data[1]
        compatibility = data[2]
        level = data[3]
        nalu_size = (data[4] & 0x03) + 1
        sps_count = data[5] & 0x1F

        # 解析SPS
        sps_list = []
        pos = 6
        for _ in range(sps_count):
            if pos + 2 > len(data): break
            sps_len = struct.unpack('>H', data[pos:pos+2])[0]
            pos += 2
            if pos + sps_len > len(data): break
            sps_list.append(data[pos:pos+sps_len])
            pos += sps_len

        # 解析PPS
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

        # 构建描述信息
        desc = f"""AVC Configuration Box
        ----------------------------
        Version: {config_version}
        Profile: {profile} ({"Baseline" if profile==66 else "Main" if profile==77 else "High"})
        Level: {level/10:.1f}
        SPS: {len(sps_list)}, PPS: {len(pps_list)}"""

        # 添加到树形视图
        item_id = self.tree.insert(
            parent_id, "end", 
            text="avcC Box",
            values=("avcC", f"{offset}", len(data), desc)
        )
        self.box_descriptions[item_id]= desc
        
        # 添加SPS/PPS子节点
        if sps_list:
            self._add_nalu(item_id, "SPS", sps_list[0], offset+16)
        if pps_list:
            self._add_nalu(item_id, "PPS", pps_list[0], offset+16+len(sps_list[0])+2)

    def _add_nalu(self, parent_id, name, nalu_data, offset):
        """添加NAL单元节点"""
        item_id = self.tree.insert(
            parent_id, "end",
            text=f"{name}",
            values=(name, f"{offset}", len(nalu_data), 
                   f"{name} (Type: 0x{nalu_data[0] & 0x1F:02X})")
        )
        self.box_hex_data[item_id] = nalu_data.hex(' ')
    
    
    
    def add_box_to_treeview(self, box_type, box_size, box_data, offset, description, hex_data, parent_id=""):
        start_address = f"{offset:d}"
        item_id = self.tree.insert(parent_id, "end", text=f"{box_type} Box", values=(box_type, start_address, box_size, description))
        if box_type in ['moov', 'trak', 'mdia', 'minf', 'stbl', 'udta', 'edts', 'moof', 'traf','dinf', 'meta','mvex', 'sinf', 'stsd', 'schi']:
            nested_offset = offset + 8  
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
            if box_type == 'hvcC':
                self.parse_hvcc(box_data, offset, parent_id)
            elif box_type == 'avcC':
                self.parse_avcc(box_data, offset, parent_id)
            else:
                description = self.get_box_description( offset, box_size, box_type, box_data)
                hex_data = self.get_hex_data(box_header+box_data, box_type)
                self.add_box_to_treeview(box_type, box_size, box_data, offset, description, hex_data, parent_id)
                offset += box_size
#
    def display_frame_info(self):
        total_frames = len(self.frame_start_positions)
        frame_positions = "\n".join([f"帧 {i + 1}: 起始位置 - {start}" for i, start in enumerate(self.frame_start_positions)])
        print(f"总帧数: {total_frames}")
      
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
            ascii_part += "  "
            ascii_part += ''.join(chr(byte) if 32 <= byte <= 126 else '.' for byte in chunk2)
            lines.append(f"{hex_part:<48}  {ascii_part}")
        return '\n'.join(lines)


       
app = None
g_fileName = ""

def select_file(root):
    file_path = filedialog.askopenfilename(title="选择文件", filetypes=[("所有文件", "*.*")])

    if file_path:
        global app
        if app != None :
            app.remove_trees()
        app = MP4ParserApp(root, file_path)
        app.display_frame_info() 

if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("1000x600")

    button = tk.Button(root, text="选择文件", command=lambda: select_file(root))
    button.pack(anchor="w", padx=10, pady=10)

    root.mainloop()
    
    
    
    
    
    
    
    
    
