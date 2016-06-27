module.exports = function(grunt) {

  var externalScriptFiles = grunt.file.readJSON('externalScripts.json');

  require('time-grunt')(grunt);

  grunt.initConfig({
    pkg: grunt.file.readJSON('package.json'),
    less: {
      compile: {
        options: {
          cleancss: true
        },
        files: { "public/styles/app.css" : 'public_src/styles/main.less' }
      }
    },
    ngAnnotate: {
      main: {
        files: {
          'grunt_tmp/angularScripts.js' : [
            'public_src/scripts/main.js',
            'public_src/scripts/controllers/*.js',
            'public_src/scripts/factories/*.js',
            'public_src/scripts/filters/*.js',
            'public_src/scripts/directives/*.js'
          ]
        }
      }
    },
    uglify: {
      options: {
        report: 'min',
        mangle: true
      },
      main: {
        files: {
          'public/scripts/app.js' : ['public/scripts/app.js']
        }
      }
    },
    copy: {
      fontawesome: {
        files: [
              { expand: true,
                cwd: "public_src/libs/bower_components/font-awesome/",
                src: "fonts/*",
                dest: "public/"
              }
        ]
      }
    },
    concat: {
      libs: {
        src: externalScriptFiles,
        dest: 'grunt_tmp/externalScripts.js',
        nonull: true
      },
      app: {
        src: [
          'grunt_tmp/externalScripts.js',
          'grunt_tmp/angularScripts.js'
        ],
        dest: 'public/scripts/app.js',
        nonull: true
      }
    },
    clean: {
      files: ['grunt_tmp/']
    },
        // use tape to define our tests
        // this is mostly for the back-end code.
        // Front-end code is all handled by testling.
        // Testling settings can be found in the package.json file.
    tape: {
      options: {
        pretty: true,
        output: 'console'
      },
      files: [
        'tests/routes/**/*.js'
      ]
    },
    watch: {
      options: {
        livereload: true,
        spawn: false
      },
      less: {
        files: ['public_src/styles/**/*.less'],
        tasks: ['less']
      },
      html: {
        files: ['public/index.html', 'public/views/**/*.html']
      },
      mainScript: {
        files: ['public_src/scripts/main.js'],
        tasks: ['clean', 'concat:libs', 'ngAnnotate', 'concat:app', 'testling']
      },
      controllers: {
        files: ['public_src/scripts/controllers/*.js'],
        tasks: ['clean', 'concat:libs', 'ngAnnotate', 'concat:app', 'testling']
      },
      factories: {
        files: ['public_src/scripts/factories/*.js'],
        tasks: ['clean', 'concat:libs', 'ngAnnotate', 'concat:app', 'testling']
      },
      filters: {
        files: ['public_src/scripts/filters/*.js'],
        tasks: ['clean', 'concat:libs', 'ngAnnotate', 'concat:app', 'testling']
      },
      directives: {
        files: ['public_src/scripts/directives/*.js'],
        tasks: ['clean', 'concat:libs', 'ngAnnotate', 'concat:app', 'testling']
      },
      externalFiles: {
        files: ['externalScripts.json', 'externalStyles.json'],
        tasks: ['clean', 'concat:libs', 'ngAnnotate', 'concat:app']
      },
            // watch front-end code:
      ngTests: {
        files: ['tests/public_src/**/*.js'],
        tasks: ['testling']
      },

            // watch back-end code:
      nodeTests: {
        files: ['server.js', 'routes/**/*.js', 'tests/routes/**/*.js'],
        tasks: ['tape']
      }
    }
  });

  grunt.loadNpmTasks('grunt-ng-annotate');
  grunt.loadNpmTasks('grunt-contrib-uglify');
  grunt.loadNpmTasks('grunt-contrib-watch');
  grunt.loadNpmTasks('grunt-contrib-less');
  grunt.loadNpmTasks('grunt-contrib-concat');
  grunt.loadNpmTasks('grunt-contrib-clean');
  grunt.loadNpmTasks('grunt-contrib-copy');
  grunt.loadNpmTasks('grunt-tape');
  grunt.loadNpmTasks('grunt-testling');

  grunt.registerTask('default', ['watch']);
  grunt.registerTask('build', ['clean', 'less', 'copy:fontawesome', 'concat:libs', 'ngAnnotate', 'concat:app', 'uglify']);

};
