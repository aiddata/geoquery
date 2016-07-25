angular.module('aiddataDET')
  .factory('queryFactory', function(ajaxFactory, $log, $q) {

    var _datasets = [],            // All Datasets
        _boundaries = {};          // All Boundaries

    var _boundary = {},            // Selected Boundary
        _subBoundary = {};         // Selected Enumeration Units

    // Current Query Object
    var _query = {
      boundary: null,
      release_data: [],
      raster_data: [],
      email: null
    };

    var _fields = { };

    function retrieveBoundaries () {
      if (!_boundaries.options) {
        return ajaxFactory.boundaries()
          .then(function(results) {
            _boundaries.options = results.data.boundaries;
            return _boundaries.options;
          });
      }
      $log.debug('Boundaries Already Defined');
      return _boundaries.options;
    }

    function retrieveDatasets (boundaryId) {
      if (!_datasets.length) {
        return ajaxFactory.datasets(boundaryId)
          .then(function(results) {
            if (!results.data.length) {
              return $q.reject('No Datasets Found');
            }

            _datasets = results.data;
            return _datasets;
          });
      }
      $log.debug('Datasets Already Defined');
      return _datasets;
    }

    function findBoundary (boundaryId) {
      return _.find(_boundaries.options, { boundaryId: boundaryId });
    }

    function findSubBoundary(boundary, subboundaryId) {
      return _.find(boundary.subBoundaries, { name: subboundaryId });
    }

    function defineBoundary (boundaryId, subboundaryId) {
      _boundary = findBoundary(boundaryId);
      _subBoundary = findSubBoundary(_boundary, subboundaryId);

      _query.boundary = {
        title: _subBoundary.title,
        group: _subBoundary.options.group,
        name: _subBoundary.name,
        description: _subBoundary.description,
        path: _subBoundary.base + _.head(_subBoundary.resources).path
      };
      return true;
    }

    function defineReleaseData (filters, filterOptions) {
      var filterData = _.chain(filterOptions)
        .get('filterTypes')
        .mapKeys()
        .mapValues(function (d) { return filters[d] || ['All']; })
        .value();

      var datasetData = _.chain(filters)
        .pick('dataset')
        .cloneDeep()
        .extend(filterData)
        .value();

      _query.release_data.push(datasetData);
      return _.cloneDeep(_query);
    }

    function defineRasterData (options, dataset) {
      var datasetData = _.chain(dataset)
        .pick(['name', 'title', 'base', 'type'])
        .extend({ temportal_type: _.get(dataset, 'temporal.type') })
        .extend(options)
        .value();

      _query.raster_data.push(datasetData);
      return _.cloneDeep(_query);
    }

    return {
      /* @TODO: Store Dataset Separately From Filters */
      filters: { },

      filterOptions: { },

      options: {
        options: { extract_types: [] },
        files: []
      },

      generateQuery: function (datasetType) {
        // Test that there are projects/locations
        var self = this;
        var addRelease = function () {
          return defineReleaseData(self.filters, self.filterOptions);
        };
        var addRaster = function () {
          var dataset = self.getDataset();
          return defineRasterData(self.options, dataset);
        };

        var addFunct = datasetType === 'release' ? addRelease : addRaster;

        return $q.when(addFunct())
        .then(function(query) {
          return query;
        });
      },

      getBoundaries: function () {
        return $q.when(retrieveBoundaries())
          .then(function(boundaries) {
            return boundaries;
          });
      },

      setBoundary: function(boundary, subboundary) {
        return $q.when(defineBoundary(boundary, subboundary));
      },

      getDatasets: function (boundaryId) {
        return $q.when(retrieveDatasets(boundaryId))
        .then(function(datasets) {
          return datasets;
        });
      },

      updateFilters: function () {
        var self = this;

        return ajaxFactory.filters(self.filters)
          .then(function(results) {
            var filterOptions = self.filterOptions = results.data;
            filterOptions.filterTypes = _.keys(filterOptions.distinct);
            return filterOptions;
          }, function(err) {
            $log.error(err);
          });
      },

      setDataset: function(datasetName) {
        this.filters.dataset = datasetName;
        return this.getDataset(datasetName);
      },

      getDataset: function(datasetName) {
        datasetName = datasetName || this.filters.dataset;

        var dataset = _.find(_datasets, { name: datasetName });
        if (!dataset) {
          $log.error('Dataset not found', datasetName, _datasets);
        }
        return _.cloneDeep(dataset);
      },

      toggleFilterOn: function(filter, option) {
        if (!this.filters[filter]) {
          this.filters[filter] = [];
        }
        if (_.includes(this.filters[filter], 'All')) {
          _.pull(this.filters[filter], 'All');
        }
        this.filters[filter].push(option);
      },

      toggleFilterOff: function (filter, option) {
        _.pull(this.filters[filter], option);
        if (!this.filters[filter].length) {
          this.filters[filter].push('All');
        }
      },

      resetFilter: function (filter) {
        this.filters[filter] = ['All'];
        return this.filters;
      },

      clearFilters: function () {
        var self = this;
        _.each(self.filters, function(d, i) {
          self.resetFilter(i);
        });
        return this.filters;
      },

      toggleOptionOn: function (key, val) {
        var optionData = _.isArray(key.pick) ? _.pick(val, key.pick) :
          _.get(val, key.pick);

        _.get(this.options, key.dest).push(optionData);

        val.checked = true;
      },

      toggleOptionOff: function (key, val) {
        var optionData = _.isArray(key.pick) ? _.pick(val, key.pick) :
          _.get(val, key.pick);

        _.pull(_.get(this.options, key.dest), optionData);

        val.checked = false;
      },

      resetOption: function (key) {
        var options = _.chain(this.options)
          .get(key)
          .each(function(val) { val.checked = false; })
          .value();

        if (options.length) {
          options.splice(0);
        }
      },
      clearOptions: function() {
        this.options.options = { extract_types: [] };
        this.options.files = [];
        return this.options;
      },

      updateFilterRange: function(min, max, filter) {
        var self = this;
        this.filters[filter] = this.filters[filter] || [];

        if (this.filters[filter].length) {
          this.filters[filter].splice(0);
        }
        _.each(_.range(min, max + 1), function(n) {
          self.filters[filter].push(n);
        });
      },

      resetFilterRange: function(filter) {
        this.filters[filter] = this.filters[filter] || [];

        if (this.filters[filter].length) {
          this.filters[filter].splice(0);
        }
        this.filters[filter].push('All');
      }
    };
  });
