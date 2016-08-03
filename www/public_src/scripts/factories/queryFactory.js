angular.module('aiddataDET')
  .factory('queryFactory', function(ajaxFactory, $log, $q, $rootScope) {

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

    function defineReleaseData (filters, filterOptions, queryName) {
      var filterData = _.chain(filterOptions)
        .get('filterTypes')
        .mapKeys()
        .mapValues(function (d) { return filters[d] || ['All']; })
        .value();

      var datasetData = _.chain(filters)
        .pick('dataset')
        .cloneDeep()
        .extend({
          custom_name: queryName,
          filters: filterData
        })
        .value();

      _query.release_data.push(datasetData);
      return _.cloneDeep(_query);
    }

    function defineRasterData (options, dataset, queryName) {
      var datasetData = _.chain(dataset)
        .pick(['name', 'title', 'base', 'type'])
        .extend({
          custom_name: queryName,
          temportal_type: _.get(dataset, 'temporal.type')
        })
        .extend(options)
        .value();

      _query.raster_data.push(datasetData);
      return _.cloneDeep(_query);
    }

    function _removeRequest (request, type) {
      var loc = _.chain(_query)
      .get(type)
      .findIndex(_.omit(request, '$$hashKey'))
      .value();

      if (loc >= 0 ) {
        _.pullAt(_query[type], loc);
        return _.cloneDeep(_query);
      } else {
        return $q.reject('Unable to locate query');
      }
    }

    return {
      /* @TODO: Store Dataset Separately From Filters */
      filters: { },

      filterOptions: { },

      options: {
        options: { extract_types: [] },
        files: []
      },

      generateQuery: function (datasetType, queryName) {
        // Test that there are projects/locations
        var self = this;
        var addRelease = function () {
          return defineReleaseData(_.cloneDeep(self.filters), _.cloneDeep(self.filterOptions), queryName);
        };
        var addRaster = function () {
          var dataset = self.getDataset();
          return defineRasterData(_.cloneDeep(self.options), _.cloneDeep(dataset), queryName);
        };

        var addFunct = datasetType === 'release' ? addRelease : addRaster;

        return $q.when(addFunct())
        .then(function(query) {
          console.log(JSON.stringify(query));
          return query;
        });
      },

      getQuery: function () {
        return _query;
      },

      isUniq: function(dataset, filters, options) {
        if (dataset.type === 'raster') {
          var fileNames = _.map(options.files, 'name').sort();
          return _.every(_query.raster_data, function(q) {
            return dataset.title !== q.title ||
              !_.isEqual(q.options.extract_types.sort(), options.options.extract_types.sort()) ||
              !_.isEqual(_.map(q.files, 'name').sort(), fileNames);
          });
        } else {
          return _.every(_query.release_data, function(q) {
            return dataset.name !== q.dataset ||
              !_.isEqual(_.keys(q.filters).sort(), _.keys(_.omit(filters, 'dataset')).sort()) ||
              !_.every(q.filters, function(queryFilter, queryFilterId) {
                return _.isEqual(queryFilter.sort(), filters[queryFilterId].sort());
              });
          });
        }
      },

      submitRequest: function(email) {
        var query = _.cloneDeep(_query);
        query.email = email;
        query.submitTime = Date.now();

        return ajaxFactory.submitRequest(JSON.stringify(query))
          .then(function(data) {
            _query.raster_data.splice(0);
            _query.release_data.splice(0);
            return data;
          }, function(err) {
            console.error(err);
          });
      },

      removeRequest: function(request, type) {
        return $q.when(_removeRequest(request, type))
        .then(function(c){ return c; });
      },

      querySize: function () {
        return _.chain(_query.raster_data)
          .map(function(d) {
            var fileSize = _.size(_.get(d, 'files')),
                extractSize = _.size(_.get(d, 'options.extract_types'));

            return fileSize * extractSize;
          })
          .sum()
          .add(_.size(_.get(_query, 'release_data')))
          .value();
      },

      getBoundaries: function () {
        return $q.when(retrieveBoundaries())
          .then(function(boundaries) {
            return boundaries;
          });
      },

      getBoundary: function() {
        return _boundary;
      },

      getSubBoundary: function () {
        return _subBoundary;
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
        this.filters[filter].splice(0);
        this.filters[filter].push('All');
        return this.filters;
      },

      clearFilters: function () {
        var self = this;
        _.each(_.omit(self.filters, 'dataset'), function(d, i) {
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
        var optionData = _.isArray(key.pick) ? _.pick(val, key.pick) : _.get(val, key.pick),
            targetArry = _.get(this.options, key.dest),
            optionIndex = _.isString(optionData) ? targetArry.indexOf(optionData) :
               _.findIndex(targetArry, optionData);

        _.pullAt(targetArry, optionIndex);

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
        this.filters[filter] = _.filter(self.filterOptions.distinct[filter], function(f) {
          return f >= min && f <= max;
        });
      },

      resetFilterRange: function(filter) {
        this.filters[filter] = this.filters[filter] || [];

        if (this.filters[filter].length) {
          this.filters[filter].splice(0);
        }
        this.filters[filter].push('All');

        $rootScope.$broadcast('filters:resetRange', { filterId: filter });
      }
    };
  });
