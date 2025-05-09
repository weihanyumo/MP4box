import re
import struct
import tkinter as tk
from tkinter import ttk
from tkinter import filedialog
import io
import sys
import time
from tkinter import simpledialog

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
            frames.append({
                'DTS': dts_list[i],
                'PTS': pts_list[i],
                'size': sizes[i],
                'offset': offsets[i]
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
        self.elst = []
        self.stts = []
        self.ctts = []
        self.stsz = []
        self.stsc = []
        self.stco = []
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
                box_size, box_type, box_data, box_header = self.read_box(file, offset)
                if not box_size:
                    break  
                description = self.get_box_description(offset, box_size, box_type, box_data)
                #description = f"size: {box_size}, des: {description}"

                
                hex_data = self.get_hex_data(box_header + box_data, box_type) 
                self.add_box_to_treeview(box_type, box_size, box_data, offset, description, hex_data)
                offset += box_size  

    def read_box(self, file, offset):
        box_header = file.read(8)
        if len(box_header) < 8:
            return None, None, None, None

        box_size, box_type = struct.unpack('>I4s', box_header)
        box_type = box_type.decode('utf-8', errors='ignore')

        box_data = file.read(box_size - 8) if box_size > 8 else b''
        #print(f"type:{box_type} size: {box_size} data_len: {len(box_data)}")
        return box_size, box_type, box_data, box_header

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
                description += f"Frame {j + 1}: PTS={frame['PTS']:.3f}, DTS={frame['DTS']:.3f}, Size={frame['size']}, offset={frame['offset']}\n"
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
            self.elst.append((segment_duration, media_time, media_rate))
            self.currentTrak.elst.append((segment_duration, media_time, media_rate))
            offset += 12
        
        return f"entry count: {entry_count}, \nchunk: {'\n'.join(map(str, self.elst))}"
        
    def get_stts_description(self, box_data):
        entry_count = struct.unpack('>I', box_data[4:8])[0]
        sample_data = []
        frame_start_time = 0
        index = 8 
        for _ in range(entry_count):
            count, sample_delta  = struct.unpack('>II', box_data[index:index+8])
            index += 8
            self.stts.append((count, sample_delta ))
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
            self.ctts.append((count, composition_delta))
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
            self.stss.append(sync_sample)
        return f"sync sample count： {entry_count}  \nsync samples: {'\n'.join(map(str, self.stss))}"
        
    def get_stsz_description(self, box_data):
        verflag, sample_size = struct.unpack('>II', box_data[:8])
        sample_count = struct.unpack('>I', box_data[8:12])[0]
        offset = 12
        if sample_size == 0:
            for _ in range(sample_count):
                entry_size = struct.unpack('>I', box_data[offset:offset + 4])[0]
                self.stsz.append(entry_size)
                self.currentTrak.stsz.append(entry_size)
                offset += 4
        else:
            self.stsz = [sample_size] * sample_count
        return f"sample_size:{sample_size}sample count： {sample_count} \n sizes: {'\n'.join(map(str, self.stsz))}"
           
    def get_stsc_description(self, box_data):
        entry_count = struct.unpack('>I', box_data[4:8])[0]
        offset = 8
        for _ in range(entry_count):
            first_chunk, samples_per_chunk, sample_desc_idx = struct.unpack('>III', box_data[offset:offset + 12])
            self.stsc.append((first_chunk, samples_per_chunk, sample_desc_idx))
            self.currentTrak.stsc.append((first_chunk, samples_per_chunk, sample_desc_idx))
            offset += 12
        return f"entry count: {entry_count}, \nchunks: {'\n'.join(map(str, self.stsc))}"
        
    def get_stco_description(self, box_data):
        entry_count = struct.unpack('>I', box_data[4:8])[0]
        offset = 8
        for _ in range(entry_count):
            chunk_offset = struct.unpack('>I', box_data[offset:offset + 4])[0]
            self.stco.append(chunk_offset)
            self.currentTrak.stco.append(chunk_offset)
            offset += 4
        return f"entry count: {entry_count} \nchunk: {'\n'.join(map(str, self.stco))}"
        
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
            box_size, box_type, box_data, box_header = self.read_box(io.BytesIO(box_data), offset)
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
            box_size, box_type, box_data, box_header = self.read_box(io.BytesIO(box_data), offset)
            description += f"子 Box 类型: {box_type}, 大小: {box_size}\n"
            if box_type == "tfhd":
                description += self.get_tfhd_description(box_data)
            elif box_type == "trun":
                description += self.get_trun_description(startPos, box_data)
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
            user_input = simpledialog.askinteger("输入timescale数值", "请输入timeScale：（从init mp4读）")
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
            sample_info.append(f"pts:{samplePresentationTime/self.currentTrak.timescale}")

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
    def get_tfhd_description(self, box_data):
        track_id = struct.unpack('>I', box_data[0:4])[0]
        flags = struct.unpack('>I', box_data[4:8])[0]
        description = f"track ID: {track_id}, flags: {flags}"
   
        self.currentTrak = self.get_or_create_track(track_id)
        
        if flags & 0x00000001: 
            default_sample_duration = struct.unpack('>I', box_data[8:12])[0]
            self.currentTrak.duration = default_sample_duration
            description += f", default sample duration: {default_sample_duration}"

        if flags & 0x00000002: 
            default_sample_size = struct.unpack('>I', box_data[12:16])[0]
            description += f", 默认样本大小: {default_sample_size}"

        return description

    def get_vmhd_description(self, box_data):
        """
        1	version	版本号，通常是 0
        3	flags	标志位，一般为 1 表示图像需要合成
        2	graphicsmode	图像合成模式，0 表示直接拷贝
        2	opcolor[0]	红色通道的默认合成值
        2	opcolor[1]	绿色通道的默认合成值
        2	opcolor[2]	蓝色通道的默认合成值
        """
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
        

    def add_box_to_treeview(self, box_type, box_size, box_data, offset, description, hex_data, parent_id=""):
        start_address = f"{offset:d}"
        item_id = self.tree.insert(parent_id, "end", text=f"{box_type} Box", values=(box_type, start_address, box_size, description))
        if box_type in ['moov', 'trak', 'mdia', 'minf', 'stbl', 'udta', 'edts', 'moof', 'traf','dinf', 'meta']:
            nested_offset = offset + 8  
            if box_type == 'meta':
                nested_offset = offset + 12
                box_data = box_data[4:]
            self.read_nested_boxes(io.BytesIO(box_data), nested_offset, item_id)
        self.box_descriptions[item_id] = description  
        self.box_hex_data[item_id] = hex_data 
        if box_type == 'mdat':
            self.mdat_item_id = item_id;

    def read_nested_boxes(self, box_file, offset, parent_id):
        while True:
            box_size, box_type, box_data, box_header = self.read_box(box_file, offset)
            if not box_size:
                break
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
            hex_part = ' '.join(f"{byte:02X}" for byte in chunk)
            ascii_part = ''.join(chr(byte) if 32 <= byte <= 126 else '.' for byte in chunk)
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
    
    
    
    
    
    
    
    
    
