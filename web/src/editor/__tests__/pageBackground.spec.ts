/**
 * 页面背景样式（编辑器画布与运行态共用唯一实现）：
 * 底色层 + 图片层分离，图片层独立不透明度（页面 opacity 会把内容一起变淡）。
 * 运行：cd web && npm test
 */
import { describe, expect, it } from 'vitest'
import { pageBaseStyle, pageImageStyle } from '@/editor/pageBackground'

describe('pageBaseStyle', () => {
  it('返回页面底色', () => {
    expect(pageBaseStyle({ color: '#123456' })).toEqual({ backgroundColor: '#123456' })
  })

  it('缺色回退默认底色', () => {
    expect(pageBaseStyle({ color: '' })).toEqual({ backgroundColor: '#0b1220' })
  })

  it('无背景配置（旧 doc）回退默认底色', () => {
    expect(pageBaseStyle(null)).toEqual({ backgroundColor: '#0b1220' })
  })
})

describe('pageImageStyle', () => {
  it('无图片或空白图片返回 null', () => {
    expect(pageImageStyle({ color: '#000' })).toBeNull()
    expect(pageImageStyle({ color: '#000', image: '   ' })).toBeNull()
  })

  it('缺省铺满裁切、居中不重复、全不透明', () => {
    expect(pageImageStyle({ color: '#000', image: '/bg/tech-grid.svg' })).toEqual({
      backgroundImage: 'url("/bg/tech-grid.svg")',
      backgroundSize: 'cover',
      backgroundPosition: 'center',
      backgroundRepeat: 'no-repeat',
      opacity: 1,
    })
  })

  it('contain 保持比例留边', () => {
    expect(pageImageStyle({ color: '#000', image: '/bg/a.svg', imageFit: 'contain' }))
      .toMatchObject({ backgroundSize: 'contain' })
  })

  it('stretch 拉满设计尺寸', () => {
    expect(pageImageStyle({ color: '#000', image: '/bg/a.svg', imageFit: 'stretch' }))
      .toMatchObject({ backgroundSize: '100% 100%' })
  })

  it('图片不透明度独立生效', () => {
    expect(pageImageStyle({ color: '#000', image: '/bg/a.svg', imageOpacity: 0.4 }))
      .toMatchObject({ opacity: 0.4 })
  })

  it('URL 中的引号与反斜杠转义，防截断样式', () => {
    expect(pageImageStyle({ color: '#000', image: 'https://x/a"b\\c.png' })?.backgroundImage)
      .toBe('url("https://x/a\\"b\\\\c.png")')
  })
})
