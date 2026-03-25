from enum import Enum, auto
from re import escape
import sys
import token

class ErrorCode(Enum):
    ILLEGAL_CHAR = 101        # 非法字符，如 #、@、¥ 等
    INVALID_TOKEN = 102       # 不符合构词规则，如非法标识符、小数点后无数字
    UNCLOSED_COMMENT = 103    # 注释未闭合，缺少 */
    UNCLOSED_CHAR = 104       # 字符类型缺少配对的 '
    UNCLOSED_STRING = 105     # 字符串类型缺少配对的 "


#枚举类定义token类型
class TokenType(Enum):
    # 关键字
    CHAR = 101
    INT = 102
    FLOAT = 103
    BREAK = 104
    CONST = 105
    RETURN = 106
    VOID = 107
    CONTINUE = 108
    DO = 109
    WHILE = 110
    IF = 111
    ELSE = 112
    FOR = 113
    
    # 界符
    LBRACE = 301      # {
    RBRACE = 302      # }
    SEMICOLON = 303   # ;
    COMMA = 304       # ,
    
    # 运算符（编码201-220）
    LPAREN = 201      # (
    RPAREN = 202      # )
    LBRACKET = 203    # [
    RBRACKET = 204    # ]
    NOT = 205         # !
    MULTIPLY = 206    # *
    DIVIDE = 207      # /
    MOD = 208         # %
    PLUS = 209        # +
    MINUS = 210       # -
    LT = 211          # <
    LE = 212          # <=
    GT = 213          # >
    GE = 214          # >=
    EQ = 215          # ==
    NE = 216          # !=
    AND = 217         # &&
    OR = 218          # ||
    ASSIGN = 219      # =
    DOT = 220

    # 单词类别
    NUMBER = 400      # 整数
    FLOAT_NUM = 800   # 实数（float）
    STRING = 600      # 字符串
    CHAR_LITERAL = 500  # 字符
    IDENTIFIER = 700  # 标识符
    
    # 特殊
    EOF = 0

KEYWORDS = {
    'char': TokenType.CHAR,
    'int': TokenType.INT,
    'float': TokenType.FLOAT,
    'break': TokenType.BREAK,
    'const': TokenType.CONST,
    'return': TokenType.RETURN,
    'void': TokenType.VOID,
    'continue': TokenType.CONTINUE,
    'do': TokenType.DO,
    'while': TokenType.WHILE,
    'if': TokenType.IF,
    'else': TokenType.ELSE,
    'for': TokenType.FOR,
}   #字典

class Token:
    def __init__(self,lexeme,token_type,line):
        self.lexeme = lexeme
        self.token_type = token_type
        self.line = line

    def __str__(self):
        return f"{self.lexeme:<15} {self.token_type.value:<5} {self.line}"

class LexialAnalyzer:
    def __init__(self,test_code):
        self.source = test_code         #string
        self.pos = 0                    #index
        self.line = 1                   #line
        #当前字符 如果为空就是 '\0'
        self.current_char = self.source[0] if test_code else '\0'
        self.errors = []  # 收集所有错误

    #预看下一个字符
    def peek(self):
        peek_pos = self.pos + 1
        if peek_pos >= len(self.source):
            return '\0'
        return self.source[peek_pos]
    
    #前进到下一个字符
    def advance(self):
        # 先检查当前字符是否是换行符，再前进
        if self.current_char == '\n':
            self.line += 1
        self.pos += 1
        if self.pos >= len(self.source):
            self.current_char = '\0'
        else:
            self.current_char = self.source[self.pos]

    #遇到注释也要跳过
    def skip_comment(self):
        line = self.line
        if self.current_char == '/' and self.peek() == '/':
            while self.current_char != '\0' and self.current_char != '\n':
                self.advance()
        elif self.current_char == '/' and self.peek() == '*':
            self.advance()
            self.advance()
            while self.current_char != '\0':
                if self.current_char == '*' and self.peek() == '/':
                    self.advance()
                    self.advance()
                    break
                self.advance()
            if self.current_char == '\0':
                self.errors.append(f"{line} {ErrorCode.UNCLOSED_COMMENT.value}")  # 注释未闭合
                return

    #遇到空白字符就一直跳
    def skip_whitespace(self):
        while self.current_char in ' \t\n\r':
            self.advance()

    #识别字符常量
    def read_char_literal(self):
        line = self.line
        self.advance()

        if self.current_char == '\0':
            self.errors.append(f"{line} {ErrorCode.UNCLOSED_CHAR.value}")  # 字符未闭合
            return None

        if self.current_char == "'":
            self.errors.append(f"{line} {ErrorCode.INVALID_TOKEN.value}")  # 单引号内没有字符
            self.advance()  # 跳过第二个单引号，避免重复处理
            return None

        #处理转义字符
        if self.current_char == '\\':
            self.advance()
            escape_chars = {
                'n': '\n',
                't': '\t',
                'r': '\r',
                '\\': '\\',
                "'": "'",
                '0': '\0',
            }
            if self.current_char in escape_chars:
                char_value = '\\' + self.current_char   #保存为\n
                self.advance()
            else:
                self.errors.append(f"{line} {ErrorCode.INVALID_TOKEN.value}")  # 非法转义字符
                # 跳过到下一个单引号或行尾
                while self.current_char not in "'\n\0":
                    self.advance()
                if self.current_char == "'":
                    self.advance()  # 跳过闭合的单引号
                return None
        else:
            char_value = self.current_char
            self.advance()

        if self.current_char != "'":
            if self.current_char.isalpha():
                self.errors.append(f"{self.line} {ErrorCode.INVALID_TOKEN.value}")  # 长度大于1
                # 跳过到下一个单引号或行尾，避免重复报错
                while self.current_char not in "'\n\0":
                    self.advance()
                if self.current_char == "'":
                    self.advance()  # 跳过闭合的单引号
                return None
            else:
                self.errors.append(f"{self.line} {ErrorCode.UNCLOSED_CHAR.value}")  # 未闭合
                # 不需要跳过，因为已经到行尾或文件结束
                return None
        self.advance()  #跳过 '

        return Token(char_value,TokenType.CHAR_LITERAL,line)

    #识别十六进制
    def read_hex_number(self,prefix):
        line = self.line
        lexeme = prefix + self.current_char
        self.advance()

        if not (self.current_char.isdigit() or self.current_char in 'abcdefABCDEF'):
            self.errors.append(f"{self.line} {ErrorCode.INVALID_TOKEN.value}")  # 非法十六进制
            return None

        while self.current_char.isdigit() or self.current_char in 'abcdefABCDEF':
            lexeme += self.current_char
            self.advance()
        # 检查十六进制后是否紧跟字母或数字（如 0x3g）
        if self.current_char.isalnum():
            self.errors.append(f"{self.line} {ErrorCode.INVALID_TOKEN.value}")  # 非法十六进制
            # 跳过整个非法部分
            while self.current_char.isalnum():
                self.advance()
            return None
        return Token(lexeme,TokenType.NUMBER,line)

    #识别整数或浮点数 包括八进制 十六进制
    def read_number(self):
        lexeme = ""
        is_float = False
        #0开头的数
        if self.current_char == '0':
            lexeme += self.current_char
            self.advance()
            if self.current_char in 'Xx':
                return self.read_hex_number(lexeme)
            elif self.current_char in '01234567':
                while self.current_char in '01234567':
                    lexeme += self.current_char
                    self.advance()
                return Token(lexeme,TokenType.NUMBER,self.line)
            
            #识别0或者0.154
            elif self.current_char == '.':
                is_float = True
                lexeme += self.current_char
                self.advance()
                #读小数部分
                if not self.current_char.isdigit():
                    self.errors.append(f"{self.line} {ErrorCode.INVALID_TOKEN.value}")  # 小数点后无数字
                    return None
                while self.current_char.isdigit():
                    lexeme += self.current_char
                    self.advance()
                if self.current_char == '.':
                    self.errors.append(f"{self.line} {ErrorCode.INVALID_TOKEN.value}")  # 小数点后还有小数点
                    return None
                # 检查小数点后是否紧跟字母（如 1.1a 这种非法格式）
                if self.current_char.isalpha():
                    self.errors.append(f"{self.line} {ErrorCode.INVALID_TOKEN.value}")  # 数字后紧跟字母
                    return None
                return Token(lexeme,TokenType.FLOAT_NUM,self.line)
            
            elif self.current_char in '89':
                self.errors.append(f"{self.line} {ErrorCode.INVALID_TOKEN.value}")  # 非法数字
                return None
            
            elif self.current_char.isalpha():
                self.errors.append(f"{self.line} {ErrorCode.INVALID_TOKEN.value}")  
                return None
            # 单独的0
            return Token(lexeme,TokenType.NUMBER,self.line)

        #普通的数
        while self.current_char.isdigit():
            lexeme += self.current_char
            self.advance()
        # 检查数字后是否紧跟字母或下划线（如 8_it5）
        if self.current_char.isalpha() or self.current_char == '_':
            self.errors.append(f"{self.line} {ErrorCode.INVALID_TOKEN.value}")  # 数字后紧跟标识符字符
            # 跳过整个非法标识符
            while self.current_char.isalnum() or self.current_char == '_':
                self.advance()
            return None
        #检查小数点
        if self.current_char == '.':
            is_float = True
            lexeme += self.current_char
            self.advance()

            #读取小数部分
            if not self.current_char.isdigit():
                self.errors.append(f"{self.line} {ErrorCode.INVALID_TOKEN.value}")  # 小数点后无数字
                return None
            while self.current_char.isdigit():
                lexeme += self.current_char
                self.advance()
            # 检查小数点后是否还有小数点（如 1.1.2）
            if self.current_char == '.':
                self.errors.append(f"{self.line} {ErrorCode.INVALID_TOKEN.value}")  # 小数点后还有小数点
                return None
            # 检查小数点后是否紧跟字母（如 1.1a 这种非法格式）
            if self.current_char.isalpha():
                self.errors.append(f"{self.line} {ErrorCode.INVALID_TOKEN.value}")  # 数字后紧跟字母
                return None
        
        if is_float:
            return Token(lexeme,TokenType.FLOAT_NUM,self.line)
        else:
            return Token(lexeme=lexeme,token_type=TokenType.NUMBER,line=self.line)

    #识别字符串
    def read_string(self):
        self.advance()  #跳过"

        lexeme = ''
        while self.current_char != '\0' and self.current_char != '"':
            #处理转移
            if self.current_char == '\\':
                self.advance()
                if self.current_char == '\0':
                    self.errors.append(f"{self.line} {ErrorCode.UNCLOSED_STRING.value}")  # 字符串未闭合
                    return None
                escape_chars = {
                    'n': '\n',
                    't': '\t',
                    'r': '\r',
                    '\\': '\\',
                    '"': '"',
                }
                if self.current_char in escape_chars:
                    lexeme += escape_chars[self.current_char] 
                    self.advance()
                else:
                    self.errors.append(f"{line} {ErrorCode.INVALID_TOKEN.value}")  # 非法转义字符
                    # 跳过到字符串结束或行尾
                    while self.current_char not in '"\n\0':
                        self.advance()
                    if self.current_char == '"':
                        self.advance()  # 跳过闭合引号
                    return None
            else:
                lexeme += self.current_char
                self.advance()
        #判断结束的原因
        if self.current_char != '"':
            self.errors.append(f"{line} {ErrorCode.UNCLOSED_STRING.value}")  # 字符串未闭合
            return None
        
        self.advance()
        return Token(lexeme,TokenType.STRING,line)

    #识别标识符和关键字
    def read_identifier(self):
        lexeme = ""
        #状态IN_ID
        while self.current_char.isalnum() or self.current_char == '_':
            lexeme += self.current_char
            self.advance()

        token_type = KEYWORDS.get(lexeme,TokenType.IDENTIFIER)
        return Token(lexeme, token_type, self.line)

    #识别运算符和界符
    def read_operator(self):
        char = self.current_char
        line = self.line

        #双字符 需要超前一个读 认出来了就要前进到双字符之后的一个字符
        if char == '=':
            self.advance()
            if self.current_char == '=':
                self.advance()
                return Token('==',TokenType.EQ,line)
            return Token('=',TokenType.ASSIGN,line)
        elif char == '<':
            self.advance()
            if self.current_char == '=':
                self.advance()  #判断出来了就要前进一个字符
                return Token('<=',TokenType.LE,line)
            return Token('<',TokenType.LT,line)
        elif char == '>':
            self.advance()
            if self.current_char == '=':
                self.advance()
                return Token('>=',TokenType.GE,line)
            return Token('>',TokenType.GT,line)
        elif char == '!':
            self.advance()
            if self.current_char == '=':
                self.advance()
                return Token('!=',TokenType.NE,line)
            return Token("!",TokenType.NOT,line)
        elif char == '&':
            self.advance()
            if self.current_char == '&':
                self.advance()
                return Token("&&",TokenType.AND,line)
            self.errors.append(f"{line} {ErrorCode.INVALID_TOKEN.value}")  # 非法运算符
            return None
        elif char == '|':
            self.advance()
            if self.current_char == '|':
                self.advance()
                return Token('||',TokenType.OR,line)
            self.errors.append(f"{line} {ErrorCode.INVALID_TOKEN.value}")  # 非法运算符
            return None
    
        #单字符运算符和界符
        self.advance()
        token_map = {
            '+': TokenType.PLUS,
            '-': TokenType.MINUS,
            '*': TokenType.MULTIPLY,
            '/': TokenType.DIVIDE,
            '%': TokenType.MOD,
            ';': TokenType.SEMICOLON,
            '(': TokenType.LPAREN,
            ')': TokenType.RPAREN,
            '{': TokenType.LBRACE,
            '}': TokenType.RBRACE,
            '[': TokenType.LBRACKET,
            ']': TokenType.RBRACKET,
            ',': TokenType.COMMA,
            '.': TokenType.DOT,
        }

        if char in token_map:
            return Token(char, token_map[char], line)
        
        self.errors.append(f"{line} {ErrorCode.ILLEGAL_CHAR.value}")  # 非法字符
        return None
    
    #获取Token
    def get_next_token(self):

        while self.current_char != '\0':
            #非法字符 # @ $ 或中文字符
            if self.current_char in '@#$' or ('\u4e00' <= self.current_char <= '\u9fff'):
                self.errors.append(f"{self.line} {ErrorCode.ILLEGAL_CHAR.value}")  # 非法字符
                # 跳过连续的所有非法字符，避免重复报错
                while self.current_char in '@#$' or ('\u4e00' <= self.current_char <= '\u9fff'):
                    self.advance()
                continue
            #空白字符
            if self.current_char in ' \t\n\r':
                self.skip_whitespace()
                continue
            #//
            if self.current_char == '/' and self.peek() == '/':
                self.skip_comment()
                continue
            #/*
            if self.current_char == '/' and self.peek() == '*':
                self.skip_comment()
                continue     
            #字符常量 'a' or '\n'
            if self.current_char == "'":
                return self.read_char_literal()
            #字符串
            if self.current_char == '"':
                return self.read_string()
            #数字
            if self.current_char.isdigit():
                return self.read_number()
            #标识符和关键字
            if self.current_char.isalpha() or self.current_char == '_':
                return self.read_identifier()
            #运算符和界符
            return self.read_operator()
        #文件结束
        return Token('',TokenType.EOF,self.line)

    #词法分析
    def analyze(self):
        tokens = []
        while True:
            token = self.get_next_token()
            if token is None:
                continue
            if token.token_type == TokenType.EOF:
                break
            tokens.append((token.token_type,token.lexeme,token.line))
        # 输出所有错误
        if self.errors:
            for error in self.errors:
                print(error)
            return []
        return tokens

if __name__ == '__main__':
    with open('1.txt','r',encoding='utf-8') as f:
        test_code = f.read()
    analyzer = LexialAnalyzer(test_code)
    result = analyzer.analyze()
    if result:
        for i,(code,content,row) in enumerate(result):
            t = Token(content,code,row)
            print(t)
