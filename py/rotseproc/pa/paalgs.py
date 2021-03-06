"""
ROTSE-III Pipeline Algorithms
"""
import os, sys
import glob
import numpy as np
from astropy.io import fits 
from astropy.table import Table
from rotseproc.pa import pas
from rotseproc import exceptions, rlogger

rlog = rlogger.rotseLogger("ROTSE-III",20)
log = rlog.getlog()


class Find_Data(pas.PipelineAlg):
    """
    This PA finds preprocessed images for each night
    """
    def __init__(self, name, config, logger=None):
        if name is None or name.strip() == "":
            name = "Find_Data"
        datatype = fits.hdu.hdulist.HDUList
        pas.PipelineAlg.__init__(self, name, datatype, datatype, config, logger)

    def run(self, *args, **kwargs):
        if len(args) == 0 :
            log.critical("Missing input parameter!")
            sys.exit()
        if not self.is_compatible(type(args[0])):
            log.critical("Incompatible input!")
            sys.exit("Was expecting {} got {}".format(type(self.__inpType__),type(args[0])))

        night = kwargs['Night']
        if night is None:
            log.critical("Must provide night as a command line argument!")
            sys.exit("The Find_Data PA requires nights to find data...")

        program   = kwargs['Program']
        telescope = kwargs['Telescope']
        field     = kwargs['Field']
        ra        = kwargs['RA']
        dec       = kwargs['DEC']
        t_before  = kwargs['TimeBeforeDiscovery']
        t_after   = kwargs['TimeAfterDiscovery']
        datadir   = kwargs['datadir']
        datadir   = kwargs['datadir']
        outdir   = kwargs['outdir']

        return self.run_pa(program, night, telescope, field, ra, dec, t_before, t_after, datadir, outdir)

    def run_pa(self, program, night, telescope, field, ra, dec, t_before, t_after, datadir, outdir):
        # Get data
        if program == 'supernova':
            from rotseproc.io.supernova import find_supernova_field, find_supernova_data
            from rotseproc.io.preproc import match_image_prod

            # Find supernova data
            if field is None:
                if ra is None or dec is None:
                    log.critical("Must provide either the supernova field or coordinates!")
                else:
                    field = find_supernova_field(ra, dec)
                if field is None:
                    log.critical("No supernova fields contain data for these coordinates.")

            allimages, allprods, field = find_supernova_data(night, telescope, field, t_before, t_after, datadir)

            # Remove image files without corresponding prod file
            images, prods = match_image_prod(allimages, allprods, telescope, field)

        else:
            log.critical("Program {} is not valid, can't find data...".format(program))
            sys.exit()

        # Copy preprocessed images to output directory
        from rotseproc.io.preproc import copy_preproc
        copy_preproc(images, prods, outdir)

        return


class Coaddition(pas.PipelineAlg):
    """
    This PA coadds preprocessed images for each night
    """
    def __init__(self, name, config, logger=None):
        if name is None or name.strip() == "":
            name = "Coaddition"
        datatype = fits.hdu.hdulist.HDUList
        pas.PipelineAlg.__init__(self, name, datatype, datatype, config, logger)

    def run(self, *args, **kwargs):
        if len(args) == 0 :
            log.critical("Missing input parameter!")
            sys.exit()
        if not self.is_compatible(type(args[0])):
            log.critical("Incompatible input!")
            sys.exit("Was expecting {} got {}".format(type(self.__inpType__),type(args[0])))

        outdir = kwargs['outdir']

        return self.run_pa(outdir)

    def run_pa(self, outdir):
        # Set up IDL commands
        idl = "singularity run --bind /scratch /hpc/applications/idl/idl_8.0.simg"
        preprocdir = outdir + '/preproc/'
        imagedir = preprocdir + 'image/'
        files = "file_search('{}*')".format(imagedir)

        # Run coaddition
        os.chdir(preprocdir)
        os.system('{} -32 -e "coadd_all,{}"'.format(idl, files))

        # Make coadd directories
        coadddir = outdir + '/coadd/'
        os.mkdir(coadddir)
        os.mkdir(coadddir + '/image')
        os.mkdir(coadddir + '/prod')

        # Move coadds to coadd directory
        coadds = glob.glob('*000-000_c.fit')
        for c in coadds:
            os.replace(c, os.path.join(coadddir, 'image', c))

        # Find coadded images to pass to QAs
        coadd_files = glob.glob(coadddir + 'image/*')

        return coadd_files


class Source_Extraction(pas.PipelineAlg):
    """
    This PA uses SExtractor to extract sources (to do: return cobj files)
    """
    def __init__(self, name, config, logger=None):
        if name is None or name.strip() == "":
            name="Source_Extraction"

        datatype = fits.hdu.hdulist.HDUList
        pas.PipelineAlg.__init__(self, name, datatype, datatype, config, logger)

    def run(self,*args,**kwargs):
        if len(args) == 0 :
            log.critical("Missing input parameter!")
            sys.exit()
        if not self.is_compatible(type(args[0])):
            log.critical("Incompatible input!")
            sys.exit("Was expecting {} got {}".format(type(self.__inpType__),type(args[0])))

        outdir = kwargs['outdir']

        return self.run_pa(outdir)

    def run_pa(self, outdir):
        # Set up sextractor environment
        extract_par = '/scratch/group/astro/rotse/software/products/idltools/umrotse_idl/tools/sex/'
        extract_config = '/scratch/group/astro/rotse/software/products/idltools/umrotse_idl/tools/sex/'

        # Run sextractor on each coadded image
        coadddir = outdir + '/coadd'
        os.chdir(coadddir)
        coadds = os.listdir(coadddir+'/image')
        n_files = len(coadds)
        idl = "singularity run --bind /scratch /hpc/applications/idl/idl_8.0.simg"
        singularity = "singularity shell --bind /scratch /hpc/applications/rotsesoftware/rotsesoftware.simg"
        for i in range(n_files):
            # Set up output files
            conf = {'sobjdir':'', 'root':'', 'cimg':'', 'sobj':'', 'cobj':''}
            conf['sobjdir'] = coadddir+'/prod/'
            basename = coadds[i].split('000-000')[0]
            coaddname = basename + '000-000'
            conf['root'] = coaddname
            conf['cimg'] = coadddir + '/image/' + coaddname + '_c.fit'
            conf['sobj'] = coadddir + '/prod/' + coaddname + '_sobj.fit'
            conf['cobj'] = coadddir + '/prod/' + coaddname + '_cobj.fit'
            skyname = coadddir + '/prod/' + coaddname + '_sky.fit'

            # Get saturation level
            chdr = fits.open(conf['cimg'])[0].header
            satlevel = str(chdr['SATCNTS'])

            # Run sextractor
            cmd = 'sex ' + conf['cimg'] + ' -c ' + extract_par + '/rotse3.sex -PARAMETERS_NAME ' + extract_par + '/rotse3.par -FILTER_NAME ' + extract_config + '/gauss_2.0_5x5.conv -PHOT_APERTURES 7 -SATUR_LEVEL ' + satlevel + ' -CATALOG_NAME ' + conf['sobj'] + ' -CHECKIMAGE_NAME ' + skyname
            os.system(cmd)

           # Calibrate sobj file
           # os.system('{} -32 -e "run_cal,{}"'.format(idl, [coadds[i]]))

        # Login to singularity and generate cobj files
        log.info("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        log.info("!!! Logging into singularity. Make cobj files !!!")
        log.info("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        os.system(singularity)

        return


class Make_Subimages(pas.PipelineAlg):
    """
    This PA makes subimages centered around transient
    """
    def __init__(self,name,config,logger=None):
        if name is None or name.strip() == "":
            name="Make_Subimages"

        datatype = fits.hdu.hdulist.HDUList
        pas.PipelineAlg.__init__(self, name, datatype, datatype, config, logger)

    def run(self,*args,**kwargs):
        if len(args) == 0 :
            log.critical("Missing input parameter!")
            sys.exit()
        if not self.is_compatible(type(args[0])):
            log.critical("Incompatible input!")
            sys.exit("Was expecting {} got {}".format(type(self.__inpType__),type(args[0])))

        program   = kwargs['Program']
        telescope = kwargs['Telescope']
        ra        = kwargs['RA']
        dec       = kwargs['DEC']
        pixrad    = kwargs['PixelRadius']
        tempdir   = kwargs['tempdir']
        outdir    = kwargs['outdir']

        return self.run_pa(program, telescope, ra, dec, pixrad, tempdir, outdir)

    def run_pa(self, program, telescope, ra, dec, pixrad, tempdir, outdir):
        if program == 'supernova':
            from rotseproc.io.supernova import find_reference_image
            find_reference_image(telescope, tempdir, outdir)

        # Make subimages
        idl = "singularity run --bind /scratch /hpc/applications/idl/idl_8.0.simg"
        coadddir = outdir + '/coadd/'
        files = os.listdir(coadddir+'/image')
        os.chdir(coadddir)
        os.system('{} -32 -e "make_rotse3_subimage,{},racent={},deccent={},pixrad={}"'.format(idl, files, ra, dec, pixrad))

        # Move subimages to sub directory
        subdir = os.path.join(outdir, 'sub')
        os.mkdir(subdir)
        os.mkdir(os.path.join(subdir, 'image'))
        os.mkdir(os.path.join(subdir, 'prod'))

        images = glob.glob('*_c.fit')
        for i in images:
            os.replace(i, os.path.join(subdir, 'image', i))
        prods = glob.glob('*_cobj.fit')
        for p in prods:
            os.replace(p, os.path.join(subdir, 'prod', p))

        return


class Image_Differencing(pas.PipelineAlg):
    """
    This PA performs image differencing
    """
    def __init__(self,name,config,logger=None):
        if name is None or name.strip() == "":
            name="Image_Differencing"

        datatype = fits.hdu.hdulist.HDUList
        pas.PipelineAlg.__init__(self, name, datatype, datatype, config, logger)

    def run(self,*args,**kwargs):
        if len(args) == 0 :
            log.critical("Missing input parameter!")
            sys.exit()
        if not self.is_compatible(type(args[0])):
            log.critical("Incompatible input!")
            sys.exit("Was expecting {} got {}".format(type(self.__inpType__),type(args[0])))

        outdir = kwargs['outdir']

        return self.run_pa(outdir)

    def run_pa(self, outdir):
        # Run image differencing on all subimages
        subdir = os.path.join(outdir, 'sub')
        imdir = os.path.join(subdir, 'image')
        os.chdir(subdir)
        os.system('module swap python/2; difference_all.py -i {}; module swap python/3'.format(imdir))

        return


class Choose_Refstars(pas.PipelineAlg):
    """
    This PA chooses reference stars
    """
    def __init__(self,name,config,logger=None):
        if name is None or name.strip() == "":
            name="Choose_Refstars"

        datatype = fits.hdu.hdulist.HDUList
        pas.PipelineAlg.__init__(self, name, datatype, datatype, config, logger)

    def run(self,*args,**kwargs):
        if len(args) == 0 :
            log.critical("Missing input parameter!")
            sys.exit()
        if not self.is_compatible(type(args[0])):
            log.critical("Incompatible input!")
            sys.exit("Was expecting {} got {}".format(type(self.__inpType__),type(args[0])))

        ra     = kwargs['RA']
        dec    = kwargs['DEC']
        outdir = kwargs['outdir']

        return self.run_pa(ra, dec, outdir)

    def run_pa(self, ra, dec, outdir):
        # Find template subimage
        subdir = os.path.join(outdir, 'sub')
        images = sorted(os.listdir(os.path.join(subdir, 'image')))
        # Check whether template was taken before or after supernova
        if images[0][:2] != images[1][:2] and images[0][2:6] != '1231':
            template = images[0]
        elif images[0][2:6] == '1231' and int(images[0][:2]) == int(images[1][:2]) - 1:
            template = images[-1]
        else:
            template = images[-1]

        # Open rphot GUI and choose ref stars
        idl = "singularity run --bind /scratch /hpc/applications/idl/idl_8.0.simg"
        os.chdir(subdir)
        ref = "file_search('image/{}')".format(template)
        os.system('{} -32 -e "rphot,data,imlist={},refname={},targetra={},targetdec={},/small"'.format(idl, ref, ref, ra, dec))

        return


class Photometry(pas.PipelineAlg):
    """
    This PA performs image differencing
    """
    def __init__(self,name,config,logger=None):
        if name is None or name.strip() == "":
            name="Photometry"

        datatype = fits.hdu.hdulist.HDUList
        pas.PipelineAlg.__init__(self, name, datatype, datatype, config, logger)

    def run(self,*args,**kwargs):
        if len(args) == 0 :
            log.critical("Missing input parameter!")
            sys.exit()
        if not self.is_compatible(type(args[0])):
            log.critical("Incompatible input!")
            sys.exit("Was expecting {} got {}".format(type(self.__inpType__),type(args[0])))

        outdir   = kwargs['outdir']
        dumpfile = kwargs['dumpfile']

        return self.run_pa(outdir, dumpfile)

    def run_pa(self, outdir, dumpfile):
        # Do photometry
        idl = "singularity run --bind /scratch /hpc/applications/idl/idl_8.0.simg"
        subdir = os.path.join(outdir, 'sub')
        imdir = os.path.join(subdir, 'image')
        images = glob.glob(imdir + '/*sub*')
        os.chdir(subdir)

        # Make sure photometry runs on each image, move images that don't work
        nophotdir = os.path.join(subdir, 'nophot')
        os.mkdir(nophotdir)
        for image in images:
            night = os.path.basename(image)[:6]
            imfile = "file_search('image/{}*sub*')".format(night)
            os.system('{} -32 -e "run_phot,{}"'.format(idl, imfile))

            lcfile = os.path.join(subdir, 'lightcurve_subtract_target_psf.dat')
            if os.path.exists(lcfile):
                os.remove(lcfile)
            else:
                os.replace(image, os.path.join(nophotdir, os.path.basename(image)))

        if len(os.listdir(nophotdir)) == 0:
            os.rmdir(nophotdir)

        # Run photometry on all good images
        imgood = "file_search('image/*sub*')"
        os.system('{} -32 -e "run_phot,{}"'.format(idl, imgood))

        ndata = len(glob.glob(imdir + '/*sub*'))
        log.info("Ran photometry on {} nights of data".format(ndata))

        # Output light curve data and plot
        from rotseproc.pa.palib import get_light_curve_data
        from rotseproc.pa.paplots import plot_light_curve

        lc_data_file = os.path.join(subdir, 'lightcurve_subtract_target_psf.dat')
        mjd, mag, magerr = get_light_curve_data(lc_data_file)
        output = Table()
        output['MJD'] = mjd
        output['ROTSE_MAG'] = mag
        output['MAG_ERR'] = magerr
        output.write(os.path.join(outdir, 'lightcurve.fits'))

        plot_light_curve(mjd, mag, magerr, dumpfile)

        return


