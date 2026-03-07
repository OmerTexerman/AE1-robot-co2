cdc_data = None
try:
    import usb.device
    from usb.device.cdc import CDCInterface
    cdc_data = CDCInterface()
    usb.device.get().init(cdc_data, builtin_driver=True)
    print("[boot] CDC data channel ready")
except Exception as e:
    print("[boot] CDC data channel skipped: {}".format(e))
